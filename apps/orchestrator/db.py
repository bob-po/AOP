"""Shared PostgreSQL connection helpers.

Centralizes URL hardening (``sslmode=disable`` + ``connect_timeout``) and
transient-failure retry so every orchestrator module gets resilient DB
connections instead of copy-pasting a raw ``psycopg.connect``.
"""

from __future__ import annotations

import time

import psycopg
from psycopg.rows import dict_row

_CONNECT_TIMEOUT = "5"


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


def connect(url: str, *, row_factory=dict_row, retries: int = 3):
    """Open a connection, retrying transient failures.

    Docker Desktop's host->container port forwarding on Windows can fail with
    ``WSAEINVAL`` (10022) instead of a clean connection-refused during a
    container restart; a short retry masks those blips so a single failed
    connect doesn't 500 the request.

    ``row_factory=None`` yields plain tuple rows (matching a bare
    ``psycopg.connect``); the default yields dict rows.
    """
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
    raise last_exc  # type: ignore[misc]  # set after all attempts fail
