"""Phase 6 Skill System — structured skills + discovery (in-memory + optional PG)."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SkillManifest:
    name: str
    version: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    requirements: dict[str, Any] = field(default_factory=dict)
    dependencies: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    status: str = "PUBLISHED"
    providers: list[str] = field(default_factory=list)  # agent keys offering this skill

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "requirements": dict(self.requirements),
            "dependencies": dict(self.dependencies),
            "tags": list(self.tags),
            "status": self.status,
            "providers": list(self.providers),
        }

    def checksum(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SkillValidationError(ValueError):
    pass


def parse_skill(data: dict[str, Any]) -> SkillManifest:
    if not isinstance(data, dict):
        raise SkillValidationError("skill must be an object")
    name = str(data.get("name") or "").strip()
    version = str(data.get("version") or "1.0.0").strip()
    if not name:
        raise SkillValidationError("name is required")
    inputs = data.get("inputs") or data.get("input_schema") or {}
    outputs = data.get("outputs") or data.get("output_schema") or {}
    if not isinstance(inputs, dict):
        raise SkillValidationError("input_schema must be an object")
    if not isinstance(outputs, dict):
        raise SkillValidationError("output_schema must be an object")
    tags = data.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return SkillManifest(
        name=name,
        version=version,
        description=str(data.get("description") or ""),
        input_schema=dict(inputs),
        output_schema=dict(outputs),
        requirements=dict(data.get("requirements") or {}),
        dependencies=dict(data.get("dependencies") or {}),
        tags=[str(t) for t in tags],
        status=str(data.get("status") or "PUBLISHED"),
        providers=[str(p) for p in (data.get("providers") or [])],
    )


@dataclass
class SkillSearchQuery:
    skill: str | None = None
    capability: str | None = None
    input: str | None = None
    output: str | None = None
    modality: str | None = None
    resource: str | None = None
    version: str | None = None
    tenant: str | None = None
    tags: list[str] | None = None


class SkillRegistry:
    """In-process skill catalog with optional Postgres persistence."""

    def __init__(self, pool=None, *, default_tenant: str = "00000000-0000-0000-0000-000000000001"):
        self._pool = pool
        self._default_tenant = default_tenant
        self._skills: dict[str, SkillManifest] = {}
        self.discovery_count = 0
        self._seed_defaults()

    def _seed_defaults(self) -> None:
        seeds = [
            {
                "name": "image-analysis",
                "version": "1.0.0",
                "description": "Analyze images",
                "inputs": {"image": "binary"},
                "outputs": {"json": "object"},
                "tags": ["vision", "image"],
            },
            {
                "name": "image-generation",
                "version": "2.1.0",
                "description": "Generate images",
                "inputs": {"prompt": "string", "width": "integer", "height": "integer"},
                "outputs": {"image": "binary"},
                "requirements": {"gpu": True},
                "tags": ["vision", "image", "generation"],
            },
            {
                "name": "ocr",
                "version": "1.0.0",
                "description": "Optical character recognition",
                "inputs": {"image": "binary"},
                "outputs": {"text": "string"},
                "tags": ["vision", "text"],
            },
            {
                "name": "report-generation",
                "version": "1.0.0",
                "description": "Generate reports from analysis",
                "inputs": {"analysis": "object", "format": "string"},
                "outputs": {"report": "document"},
                "tags": ["document", "report"],
            },
            {
                "name": "document-analysis",
                "version": "1.0.0",
                "description": "Analyze documents",
                "inputs": {"document": "binary"},
                "outputs": {"json": "object"},
                "tags": ["document"],
            },
        ]
        for s in seeds:
            try:
                self.register(s, persist=False)
            except SkillValidationError:
                pass

    def register(self, data: dict[str, Any] | SkillManifest, *, persist: bool = True) -> SkillManifest:
        skill = data if isinstance(data, SkillManifest) else parse_skill(data)
        existing = self._skills.get(skill.name)
        if existing and existing.providers:
            # merge providers
            providers = list(dict.fromkeys([*existing.providers, *skill.providers]))
            skill.providers = providers
        self._skills[skill.name] = skill
        if persist and self._pool is not None:
            self._persist(skill)
        return skill

    def get(self, name: str) -> SkillManifest | None:
        return self._skills.get(name)

    def list(self) -> list[SkillManifest]:
        return list(self._skills.values())

    def attach_provider(self, skill_name: str, agent_key: str) -> None:
        skill = self._skills.get(skill_name)
        if skill is None:
            skill = SkillManifest(name=skill_name, version="1.0.0", description=f"Auto skill {skill_name}")
            self._skills[skill_name] = skill
        if agent_key not in skill.providers:
            skill.providers.append(agent_key)

    def search(self, query: SkillSearchQuery | dict[str, Any]) -> list[SkillManifest]:
        t0 = time.perf_counter()
        self.discovery_count += 1
        q = query if isinstance(query, SkillSearchQuery) else SkillSearchQuery(
            skill=query.get("skill") or query.get("name"),
            capability=query.get("capability"),
            input=query.get("input"),
            output=query.get("output"),
            modality=query.get("modality"),
            resource=query.get("resource"),
            version=query.get("version"),
            tenant=query.get("tenant"),
            tags=query.get("tags"),
        )
        results: list[SkillManifest] = []
        for skill in self._skills.values():
            if skill.status in ("REVOKED",):
                continue
            if q.skill and q.skill.lower() not in skill.name.lower() and q.skill.lower() not in (skill.description or "").lower():
                # also allow exact tag match later
                if q.skill not in skill.tags:
                    continue
            if q.capability and q.capability not in skill.tags and q.capability != skill.name:
                continue
            if q.input and q.input not in skill.input_schema:
                continue
            if q.output and q.output not in skill.output_schema:
                continue
            if q.modality:
                modalities = skill.tags + list(skill.input_schema.keys()) + list(skill.output_schema.keys())
                if q.modality not in modalities:
                    continue
            if q.resource:
                req = skill.requirements or {}
                # resource like "gpu" must be true or present
                if q.resource == "gpu" and not req.get("gpu"):
                    continue
                if q.resource not in req and q.resource != "gpu":
                    continue
            if q.version and q.version != skill.version and not _version_satisfies(skill.version, q.version):
                continue
            if q.tags:
                if not set(q.tags).intersection(set(skill.tags)):
                    continue
            results.append(skill)
        latency_ms = (time.perf_counter() - t0) * 1000
        logger.debug("skill_discovery count=%s latency_ms=%.2f", len(results), latency_ms)
        return results

    def providers_for(self, skill_name: str) -> list[str]:
        skill = self._skills.get(skill_name)
        return list(skill.providers) if skill else []

    def _persist(self, skill: SkillManifest) -> None:
        assert self._pool is not None
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO a2a_skills (skill_key, tenant_id, name, description, status, latest_version, tags, metadata)
                        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
                        ON CONFLICT (tenant_id, skill_key) DO UPDATE SET
                          description = EXCLUDED.description,
                          status = EXCLUDED.status,
                          latest_version = EXCLUDED.latest_version,
                          tags = EXCLUDED.tags,
                          updated_at = now()
                        RETURNING id
                        """,
                        (
                            skill.name,
                            self._default_tenant,
                            skill.name,
                            skill.description,
                            skill.status,
                            skill.version,
                            json.dumps(skill.tags),
                            json.dumps({"providers": skill.providers}),
                        ),
                    )
                    row = cur.fetchone()
                    skill_id = row[0] if row else None
                    if skill_id:
                        cur.execute(
                            """
                            INSERT INTO a2a_skill_versions
                              (skill_id, version, description, input_schema, output_schema, requirements, dependencies, status, checksum)
                            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s, %s)
                            ON CONFLICT (skill_id, version) DO UPDATE SET
                              description = EXCLUDED.description,
                              input_schema = EXCLUDED.input_schema,
                              output_schema = EXCLUDED.output_schema,
                              requirements = EXCLUDED.requirements,
                              dependencies = EXCLUDED.dependencies,
                              status = EXCLUDED.status,
                              checksum = EXCLUDED.checksum
                            """,
                            (
                                skill_id,
                                skill.version,
                                skill.description,
                                json.dumps(skill.input_schema),
                                json.dumps(skill.output_schema),
                                json.dumps(skill.requirements),
                                json.dumps(skill.dependencies),
                                "ACTIVE",
                                skill.checksum(),
                            ),
                        )
                conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("skill persist skipped: %s", exc)


def _version_satisfies(actual: str, constraint: str) -> bool:
    """Minimal semver constraint: exact, *, >=X.Y.Z, >X.Y.Z."""
    from marketplace.deps import satisfies

    return satisfies(actual, constraint)
