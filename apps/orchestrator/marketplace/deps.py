"""Phase 6 Dependency Resolver — version constraints + conflict detection."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_CONSTRAINT = re.compile(
    r"^\s*(>=|>|<=|<|==|=|~=)?\s*"
    r"([0-9]+(?:\.[0-9]+){0,2}(?:[-+][0-9A-Za-z.]+)?)\s*$"
)
_NAME_CONSTRAINT = re.compile(
    r"^\s*([A-Za-z0-9_./-]+)\s*((?:>=|>|<=|<|==|=|~=)?\s*[0-9].*)?\s*$"
)


@dataclass(frozen=True)
class Dependency:
    kind: str  # agent | skill | model | tool | runtime
    name: str
    constraint: str = "*"


@dataclass
class ResolveResult:
    ok: bool
    resolved: dict[str, str] = field(default_factory=dict)  # name -> version
    conflicts: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    graph: dict[str, list[str]] = field(default_factory=dict)


def parse_dep_spec(spec: str, *, default_kind: str = "skill") -> Dependency:
    """Parse 'ocr>=1.0' or 'vision-agent>=1.2'."""
    m = _NAME_CONSTRAINT.match(str(spec).strip())
    if not m:
        raise ValueError(f"invalid dependency: {spec}")
    name = m.group(1)
    constraint = (m.group(2) or "*").strip() or "*"
    return Dependency(kind=default_kind, name=name, constraint=constraint)


def parse_dependencies(deps: dict[str, Any] | list | None) -> list[Dependency]:
    if not deps:
        return []
    out: list[Dependency] = []
    if isinstance(deps, list):
        for item in deps:
            if isinstance(item, str):
                out.append(parse_dep_spec(item))
            elif isinstance(item, dict):
                out.append(
                    Dependency(
                        kind=str(item.get("kind") or "skill"),
                        name=str(item.get("name") or item.get("key") or ""),
                        constraint=str(item.get("constraint") or item.get("version") or "*"),
                    )
                )
        return [d for d in out if d.name]
    if not isinstance(deps, dict):
        return []
    for kind, items in deps.items():
        kind_s = str(kind).rstrip("s")  # skills -> skill
        if kind_s.endswith("ie"):  # dependencies weirdness
            pass
        if kind in ("skills", "skill"):
            kind_s = "skill"
        elif kind in ("agents", "agent"):
            kind_s = "agent"
        elif kind in ("models", "model"):
            kind_s = "model"
        elif kind in ("tools", "tool"):
            kind_s = "tool"
        elif kind in ("runtimes", "runtime"):
            kind_s = "runtime"
        else:
            kind_s = str(kind)
        if isinstance(items, list):
            for item in items:
                if isinstance(item, str):
                    out.append(parse_dep_spec(item, default_kind=kind_s))
                elif isinstance(item, dict):
                    out.append(
                        Dependency(
                            kind=kind_s,
                            name=str(item.get("name") or ""),
                            constraint=str(item.get("constraint") or item.get("version") or "*"),
                        )
                    )
        elif isinstance(items, dict):
            for name, constraint in items.items():
                out.append(Dependency(kind=kind_s, name=str(name), constraint=str(constraint or "*")))
    return [d for d in out if d.name]


def _parse_version(v: str) -> tuple[int, int, int]:
    parts = str(v).split("+")[0].split("-")[0].split(".")
    nums = []
    for i in range(3):
        try:
            nums.append(int(parts[i]) if i < len(parts) else 0)
        except ValueError:
            nums.append(0)
    return nums[0], nums[1], nums[2]


def satisfies(version: str, constraint: str) -> bool:
    c = (constraint or "*").strip()
    if c in ("*", "", "latest"):
        return True
    m = _CONSTRAINT.match(c)
    if not m:
        # bare version means exact
        return version == c
    op = m.group(1) or "=="
    target = m.group(2)
    if op in ("=", "=="):
        return _parse_version(version) == _parse_version(target)
    av, tv = _parse_version(version), _parse_version(target)
    if op == ">=":
        return av >= tv
    if op == ">":
        return av > tv
    if op == "<=":
        return av <= tv
    if op == "<":
        return av < tv
    if op == "~=":
        # compatible release: same major.minor, patch >=
        return av[0] == tv[0] and av[1] == tv[1] and av[2] >= tv[2]
    return False


class DependencyResolver:
    """
    Resolve dependency graphs against available version catalogs.

    available: {kind: {name: [versions...]}}
    """

    def resolve(
        self,
        deps: list[Dependency] | dict[str, Any] | None,
        available: dict[str, dict[str, list[str]]],
        *,
        prefer_latest: bool = True,
    ) -> ResolveResult:
        parsed = deps if isinstance(deps, list) else parse_dependencies(deps)
        result = ResolveResult(ok=True)
        # Collect constraints per (kind, name)
        constraints: dict[tuple[str, str], list[str]] = {}
        for d in parsed:
            key = (d.kind, d.name)
            constraints.setdefault(key, []).append(d.constraint)
            result.graph.setdefault(f"{d.kind}:{d.name}", [])

        for (kind, name), constrs in constraints.items():
            catalog = (available.get(kind) or {}).get(name) or []
            if not catalog:
                result.ok = False
                result.missing.append(f"{kind}:{name}")
                continue
            candidates = [v for v in catalog if all(satisfies(v, c) for c in constrs)]
            if not candidates:
                result.ok = False
                result.conflicts.append(
                    f"{kind}:{name} constraints {constrs} conflict with available {catalog}"
                )
                continue
            chosen = sorted(candidates, key=_parse_version, reverse=prefer_latest)[0]
            result.resolved[f"{kind}:{name}"] = chosen
            result.graph[f"{kind}:{name}"] = [chosen]

        # Detect direct conflicts: same name different kinds ok; same key already handled
        return result
