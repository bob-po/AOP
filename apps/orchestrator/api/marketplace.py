"""Marketplace / skills / install HTTP routes (extracted from main)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app_context import ctx, public_base_url, require_admin
from marketplace.bundle import (
    BundleError,
    attach_bundle_meta,
    build_agent_bundle,
    render_install_ps1,
    render_install_sh,
)
from marketplace.manifest import ManifestValidationError

router = APIRouter(tags=["marketplace"])


class InstallRequest(BaseModel):
    package_id: str | None = None
    endpoint: str | None = None
    version: str | None = None
    sandbox: str = "local_process"


class ManifestRegisterRequest(BaseModel):
    manifest: dict[str, Any] | None = None
    name: str | None = None
    version: str | None = None
    description: str | None = None
    author: str | None = None
    runtime: dict[str, Any] | None = None
    endpoint: str | None = None
    protocol: str | None = "a2a"
    capabilities: list[str] | None = None
    skills: list[str] | None = None
    inputs: list[str] | None = None
    outputs: list[str] | None = None
    requirements: dict[str, Any] | None = None
    permissions: list[str] | dict[str, Any] | None = None
    dependencies: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    activate: bool = True
    skip_gateway: bool = False

    def as_manifest_dict(self) -> dict[str, Any]:
        if self.manifest:
            return dict(self.manifest)
        data = self.model_dump(exclude_none=True)
        data.pop("activate", None)
        data.pop("skip_gateway", None)
        data.pop("manifest", None)
        return data


class SkillSearchRequest(BaseModel):
    skill: str | None = None
    name: str | None = None
    q: str | None = None
    capability: str | None = None
    input: str | None = None
    output: str | None = None
    modality: str | None = None
    resource: str | None = None
    version: str | None = None
    tenant: str | None = None
    tags: list[str] | None = None


class SkillRegisterRequest(BaseModel):
    name: str
    version: str = "1.0.0"
    description: str = ""
    inputs: dict[str, Any] | None = None
    outputs: dict[str, Any] | None = None
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    requirements: dict[str, Any] | None = None
    dependencies: dict[str, Any] | None = None
    tags: list[str] | None = None


class MarketplacePublishRequest(BaseModel):
    manifest: dict[str, Any]
    package_id: str | None = None
    status: str = "PUBLISHED"


class DiscoverSkillRequest(BaseModel):
    skill: str
    version: str | None = None
    version_constraint: str | None = None


def _packages_map() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for p in ctx.marketplace.catalog():
        pid = p.get("package_id")
        if pid:
            out[str(pid)] = p
    return out


def _register_manifest(body: ManifestRegisterRequest) -> dict[str, Any]:
    """Shared manifest install path (not Gateway endpoint+card registry)."""
    try:
        return ctx.marketplace.register_manifest(
            body.as_manifest_dict(),
            activate=body.activate,
            skip_gateway=body.skip_gateway,
        )
    except ManifestValidationError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "manifest_invalid", "message": str(exc)}
        ) from exc
    except PermissionError as exc:
        raise HTTPException(
            status_code=403, detail={"code": "permission_denied", "message": str(exc)}
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "validation_error", "message": str(exc)}
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502, detail={"code": "register_failed", "message": str(exc)}
        ) from exc


@router.get("/v1/marketplace")
def marketplace_catalog(request: Request, q: str | None = None) -> dict[str, Any]:
    base = public_base_url(request)
    catalog = ctx.marketplace.catalog()
    pkgs = [
        attach_bundle_meta(p, base_url=base, catalog=catalog)
        for p in ctx.marketplace.catalog(q=q)
    ]
    return {"packages": pkgs}


@router.get("/v1/marketplace/agents")
def marketplace_agents(request: Request, q: str | None = None) -> dict[str, Any]:
    base = public_base_url(request)
    catalog = ctx.marketplace.catalog()
    pkgs = [
        attach_bundle_meta(p, base_url=base, catalog=catalog)
        for p in ctx.marketplace.catalog(q=q)
    ]
    return {"packages": pkgs}


@router.post("/v1/marketplace/agents", status_code=201)
def marketplace_publish_agent(
    body: MarketplacePublishRequest, request: Request
) -> dict[str, Any]:
    require_admin(request)
    try:
        data = dict(body.manifest)
        if body.package_id:
            data["package_id"] = body.package_id
        return ctx.marketplace.publish(data, status=body.status)
    except ManifestValidationError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "manifest_invalid", "message": str(exc)}
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail={"code": "publish_failed", "message": str(exc)}
        ) from exc


@router.get("/v1/marketplace/agents/{package_id}")
def marketplace_agent_get(package_id: str, request: Request) -> dict[str, Any]:
    pkg = ctx.marketplace.get_package(package_id)
    if not pkg:
        for item in ctx.marketplace.catalog():
            if item.get("agent_key") == package_id or item.get("package_id") == package_id:
                pkg = ctx.marketplace.get_package(str(item["package_id"])) or item
                break
    if not pkg:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": package_id}
        )
    return attach_bundle_meta(
        pkg, base_url=public_base_url(request), catalog=ctx.marketplace.catalog()
    )


@router.get("/v1/marketplace/agents/{package_id}/download")
def marketplace_agent_download(package_id: str) -> Response:
    try:
        data, meta = build_agent_bundle(
            package_id,
            catalog=ctx.marketplace.catalog(),
            packages=_packages_map(),
        )
    except BundleError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "bundle_error", "message": str(exc)}
        ) from exc
    filename = meta.get("filename") or f"{package_id}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-AOP-Package-Id": str(meta.get("package_id") or package_id),
            "X-AOP-Profile": str(meta.get("profile") or ""),
            "X-AOP-Harness": str(meta.get("harness") or ""),
        },
    )


@router.get("/v1/marketplace/agents/{package_id}/install.ps1")
def marketplace_agent_install_ps1(package_id: str, request: Request) -> Response:
    try:
        script, meta = render_install_ps1(
            package_id,
            base_url=public_base_url(request),
            catalog=ctx.marketplace.catalog(),
            packages=_packages_map(),
        )
    except BundleError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "bundle_error", "message": str(exc)}
        ) from exc
    return Response(
        content=script,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="{meta["profile"]}-install.ps1"',
            "X-AOP-Install": "windows",
        },
    )


@router.get("/v1/marketplace/agents/{package_id}/install.sh")
def marketplace_agent_install_sh(package_id: str, request: Request) -> Response:
    try:
        script, meta = render_install_sh(
            package_id,
            base_url=public_base_url(request),
            catalog=ctx.marketplace.catalog(),
            packages=_packages_map(),
        )
    except BundleError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "bundle_error", "message": str(exc)}
        ) from exc
    return Response(
        content=script,
        media_type="text/x-shellscript; charset=utf-8",
        headers={
            "Content-Disposition": f'inline; filename="{meta["profile"]}-install.sh"',
            "X-AOP-Install": "unix",
        },
    )


@router.get("/install/{name}")
def install_alias(name: str, request: Request) -> Response:
    lower = name.lower()
    if lower.endswith(".ps1"):
        return marketplace_agent_install_ps1(name[: -len(".ps1")], request)
    if lower.endswith(".sh"):
        return marketplace_agent_install_sh(name[: -len(".sh")], request)
    raise HTTPException(
        status_code=404,
        detail={
            "code": "not_found",
            "message": f"use /install/<profile>.ps1 or .sh (got {name!r})",
        },
    )


@router.post("/v1/marketplace/agents/{package_id}/publish")
def marketplace_agent_publish(package_id: str) -> dict[str, Any]:
    try:
        return ctx.marketplace.publish_status(package_id, "PUBLISHED")
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": str(exc)}
        ) from exc


@router.post("/v1/marketplace/agents/{package_id}/install", status_code=201)
def marketplace_agent_install(
    package_id: str, body: InstallRequest | None = None
) -> dict[str, Any]:
    body = body or InstallRequest()
    try:
        return ctx.marketplace.install(
            package_id=package_id,
            endpoint=body.endpoint,
            version=body.version,
            sandbox=body.sandbox,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "validation_error", "message": str(exc)}
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502, detail={"code": "install_failed", "message": str(exc)}
        ) from exc


@router.post("/v1/marketplace/agents/{package_id}/activate")
def marketplace_agent_activate(package_id: str) -> dict[str, Any]:
    try:
        return ctx.marketplace.activate(package_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": str(exc)}
        ) from exc


@router.post("/v1/marketplace/agents/{package_id}/deactivate")
def marketplace_agent_deactivate(package_id: str) -> dict[str, Any]:
    try:
        return ctx.marketplace.deactivate(package_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": str(exc)}
        ) from exc


@router.post("/v1/marketplace/install", status_code=201)
def marketplace_install(body: InstallRequest) -> dict[str, Any]:
    try:
        return ctx.marketplace.install(
            package_id=body.package_id,
            endpoint=body.endpoint,
            version=body.version,
            sandbox=body.sandbox,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail={"code": "validation_error", "message": str(exc)}
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502, detail={"code": "install_failed", "message": str(exc)}
        ) from exc


@router.post("/v1/marketplace/register", status_code=201)
def marketplace_register_manifest(body: ManifestRegisterRequest) -> dict[str, Any]:
    return _register_manifest(body)


@router.post("/v1/agent-runtime/register", status_code=201)
def agent_runtime_register_manifest(body: ManifestRegisterRequest) -> dict[str, Any]:
    return _register_manifest(body)


@router.post("/v1/agent-runtime/{agent_id}/unregister")
def agents_unregister(agent_id: str, agent_key: str | None = None) -> dict[str, Any]:
    return ctx.marketplace.unregister(agent_id, agent_key=agent_key)


@router.get("/v1/skills")
def skills_list() -> dict[str, Any]:
    return {"skills": ctx.marketplace.list_skills()}


@router.get("/v1/skills/{name}")
def skills_get(name: str) -> dict[str, Any]:
    skill = ctx.marketplace.get_skill(name)
    if not skill:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": name}
        )
    return skill


@router.post("/v1/skills", status_code=201)
def skills_register(body: SkillRegisterRequest) -> dict[str, Any]:
    data = body.model_dump(exclude_none=True)
    return ctx.marketplace.register_skill(data)


@router.post("/v1/skills/search")
def skills_search(body: SkillSearchRequest) -> dict[str, Any]:
    results = ctx.marketplace.search_skills(body.model_dump(exclude_none=True))
    return {"skills": results, "count": len(results)}


@router.post("/v1/discover/skill")
def discover_skill(body: DiscoverSkillRequest) -> dict[str, Any]:
    agents = []
    try:
        agents = ctx.marketplace.list_agents()
    except Exception:  # noqa: BLE001
        agents = []
    return ctx.marketplace.discover_by_skill(
        body.skill,
        version_constraint=body.version_constraint or body.version,
        agents=agents or None,
    )


@router.post("/v1/invoke/skill")
def invoke_skill(body: DiscoverSkillRequest) -> dict[str, Any]:
    agents = ctx.marketplace.list_agents()
    return ctx.marketplace.resolve_invocation(
        body.skill,
        version_constraint=body.version_constraint or body.version,
        agents=agents or None,
        scheduling=ctx.scheduling,
    )


@router.get("/v1/marketplace/stats")
def marketplace_stats() -> dict[str, Any]:
    return {"stats": ctx.marketplace.stats}
