"""Shared PostgreSQL connection helpers.

Centralizes URL hardening (``sslmode=disable`` + ``connect_timeout``) and a
process-local connection pool. Callers keep using ``with connect(url) as conn``.

Opening a fresh TCP connection per query exhausts Windows ephemeral ports:
closed sockets sit in ``TIME_WAIT`` and the next ``connect()`` fails with
``WSAEINVAL`` (10022). The console polls task endpoints several times a
second, so the pool is what keeps those requests from 500ing.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

import psycopg
from psycopg.rows import dict_row

_CONNECT_TIMEOUT = "5"
_PING_AFTER_IDLE_S = 30.0
_POOLS: dict[tuple[Any, ...], "_Pool"] = {}
_POOLS_GUARD = threading.Lock()


def harden_database_url(url: str) -> str:
    """Ensure ``sslmode=disable`` and a ``connect_timeout`` are set.

    Native (non-Docker) runs connect to Postgres in Docker through the host's
    published port. libpq's default ``sslmode=prefer`` and a missing timeout are
    implicated in intermittent ``WSAEINVAL`` (10022) failures on Windows;
    pinning them matches the gateway's existing ``?sslmode=disable`` config.
    """
    base, _, query = url.partition("?")
    params = dict(p.split("=", 1) for p in query.split("&") if p and "=" in p)
    params.setdefault("sslmode", "disable")
    params.setdefault("connect_timeout", _CONNECT_TIMEOUT)
    return base + "?" + "&".join(f"{k}={v}" for k, v in params.items())


def _open_connection(url: str, *, row_factory, retries: int) -> psycopg.Connection:
    kwargs = {"row_factory": row_factory} if row_factory is not None else {}
    target = harden_database_url(url)
    last_exc: psycopg.OperationalError | None = None
    for attempt in range(retries):
        try:
            return psycopg.connect(target, **kwargs)
        except psycopg.OperationalError as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(0.2 * (attempt + 1))
    raise last_exc  # type: ignore[misc]


def _usable(conn: psycopg.Connection) -> bool:
    """Drop sockets the server or Windows already closed while they sat idle."""
    if conn.closed:
        return False
    idle_for = time.monotonic() - getattr(conn, "_aop_checked_at", 0.0)
    if idle_for < _PING_AFTER_IDLE_S:
        return True
    try:
        conn.execute("SELECT 1")
        conn.rollback()
        conn._aop_checked_at = time.monotonic()  # type: ignore[attr-defined]
        return True
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return False


class _Pool:
    def __init__(self, url: str, row_factory, *, max_size: int, acquire_timeout: float):
        self.url = url
        self.row_factory = row_factory
        self.max_size = max_size
        self.acquire_timeout = acquire_timeout
        self._idle: list[psycopg.Connection] = []
        self._size = 0
        self._cv = threading.Condition()

    def lease(self, *, retries: int) -> "_Lease":
        conn = self._acquire(retries=retries)
        return _Lease(self, conn)

    def _acquire(self, *, retries: int) -> psycopg.Connection:
        deadline = time.monotonic() + self.acquire_timeout
        while True:
            with self._cv:
                while self._idle:
                    conn = self._idle.pop()
                    if _usable(conn):
                        return conn
                    self._size -= 1
                    try:
                        conn.close()
                    except Exception:
                        pass
                if self._size < self.max_size:
                    self._size += 1
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise psycopg.OperationalError("postgres connection pool exhausted")
                    self._cv.wait(timeout=remaining)
                    continue
            try:
                conn = _open_connection(self.url, row_factory=self.row_factory, retries=retries)
                conn._aop_checked_at = time.monotonic()  # type: ignore[attr-defined]
                return conn
            except Exception:
                with self._cv:
                    self._size -= 1
                    self._cv.notify()
                raise

    def release(self, conn: psycopg.Connection, *, broken: bool) -> None:
        if broken or conn.closed:
            self._discard(conn)
            return
        try:
            if conn.autocommit:
                conn.autocommit = False
            conn.rollback()
            conn._aop_checked_at = time.monotonic()  # type: ignore[attr-defined]
        except Exception:
            self._discard(conn)
            return
        with self._cv:
            self._idle.append(conn)
            self._cv.notify()

    def _discard(self, conn: psycopg.Connection) -> None:
        try:
            conn.close()
        except Exception:
            pass
        with self._cv:
            self._size = max(0, self._size - 1)
            self._cv.notify()


class _Lease:
    """Context manager matching ``with psycopg.connect() as conn`` semantics.

    Commit on success, rollback on error, then return the socket to the pool
    instead of closing it.
    """

    def __init__(self, pool: _Pool, conn: psycopg.Connection):
        self._pool = pool
        self._conn = conn

    def __enter__(self) -> psycopg.Connection:
        return self._conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        broken = conn_is_broken(self._conn, exc_type, exc)
        if not broken:
            try:
                if exc_type is not None:
                    self._conn.rollback()
                elif not self._conn.autocommit:
                    self._conn.commit()
            except Exception:
                broken = True
                if exc_type is None:
                    self._pool.release(self._conn, broken=True)
                    raise
        self._pool.release(self._conn, broken=broken)
        return False


def conn_is_broken(conn: psycopg.Connection, exc_type, exc) -> bool:
    if conn.closed:
        return True
    return isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError))


def _pool_for(url: str, row_factory) -> _Pool:
    key = (harden_database_url(url), row_factory)
    with _POOLS_GUARD:
        pool = _POOLS.get(key)
        if pool is None:
            max_size = int(os.getenv("AOP_DB_POOL_MAX", "16"))
            timeout = float(os.getenv("AOP_DB_POOL_TIMEOUT", "5"))
            pool = _Pool(url, row_factory, max_size=max_size, acquire_timeout=timeout)
            _POOLS[key] = pool
        return pool


def connect(url: str, *, row_factory=dict_row, retries: int = 3):
    """Borrow a pooled connection, retrying transient connect failures.

    ``row_factory=None`` yields plain tuple rows (matching a bare
    ``psycopg.connect``); the default yields dict rows. The returned object
    is a context manager: ``with connect(url) as conn``.
    """
    return _pool_for(url, row_factory).lease(retries=retries)
