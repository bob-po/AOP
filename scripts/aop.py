#!/usr/bin/env python3
"""aop — minimal dev CLI for the A2A OS.

Thin HTTP wrapper over the OS (gateway/orchestrator) and the Agents' A2A
endpoints. No new Console/UI — just the commands needed to drive and inspect
decentralized Agent-to-Agent collaboration.

Commands:
  aop agent list | discover | health | drain | reliability | capacity | register | info
  aop skill list | search | get
  aop marketplace search | publish | install | activate | deactivate
  aop task submit | inspect | events | execution | cancel | recover | graph | cost
  aop runtime graph <root_task_id>
  aop scheduling candidates | preview | select
  aop tenant quota | budget

Env:
  A2A_OS_URL       OS base URL (default http://127.0.0.1:8080)
  A2A_OS_API_KEY   bearer key when the gateway requires auth
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

import httpx

OS_URL = (os.getenv("A2A_OS_URL") or "http://127.0.0.1:8080").rstrip("/")
API_KEY = os.getenv("A2A_OS_API_KEY")


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


def _os_post(path: str, payload: dict | None = None) -> dict:
    r = httpx.post(f"{OS_URL}{path}", json=payload or {}, headers=_headers(), timeout=60)
    r.raise_for_status()
    return r.json()


def _os_get(path: str) -> dict:
    r = httpx.get(f"{OS_URL}{path}", headers=_headers(), timeout=60)
    r.raise_for_status()
    return r.json()


def _agent_rpc(endpoint: str, method: str, params: dict) -> dict:
    r = httpx.post(
        endpoint.rstrip("/") + "/",
        json={"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params},
        timeout=90,
    )
    r.raise_for_status()
    return r.json()


def _agents() -> list[dict]:
    data = _os_get("/v1/agents")
    return (data.get("agents", data) if isinstance(data, dict) else data) or []


def _name_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for a in _agents():
        aid = a.get("agent_id") or a.get("id")
        key = a.get("agent_key") or a.get("name")
        if aid:
            out[str(aid)] = key or str(aid)
        if key:
            out[str(key)] = key
    return out


def _print_tree(tree: list[dict], names: dict[str, str], indent: int = 1) -> None:
    def nm(x):
        return names.get(str(x), str(x))

    for node in tree:
        print(
            f"{'  ' * indent}{nm(node['caller_agent_id'])} -> {nm(node['target_agent_id'])} "
            f"[skill={node['skill']} depth={node['depth']} status={node['status']} "
            f"task={node['task_id']}]"
        )
        _print_tree(node.get("children", []), names, indent + 1)


def cmd_agent_list(_args) -> int:
    agents = _agents()
    online = [a for a in agents if a.get("status") == "online"]
    print(f"{len(online)}/{len(agents)} agents online   (OS: {OS_URL})")
    for a in sorted(agents, key=lambda x: (x.get("status") != "online", x.get("agent_key") or "")):
        skills = ",".join(a.get("skills") or []) or "-"
        print(
            f"  [{a.get('status'):<7}] {(a.get('agent_key') or a.get('name')):<16} "
            f"{a.get('endpoint',''):<26} {skills}"
        )
    return 0


def cmd_agent_discover(args) -> int:
    disc = _os_post(
        "/v1/discover",
        {"required_skills": [args.skill], "limit": args.limit},
    )
    cands = disc.get("candidates") or []
    print(f"discover skill={args.skill!r} -> {len(cands)} candidate(s); selected={disc.get('selected')}")
    for c in cands:
        print(
            f"  [{c.get('status'):<7}] {c.get('agent_key'):<16} "
            f"{c.get('endpoint',''):<26} score={c.get('score')}"
        )
    return 0


def cmd_task_submit(args) -> int:
    skill = args.skill or args.agent
    sel = _os_post("/v1/route", {"skill": skill, "required_skills": [skill]}).get("selected_agent")
    if not sel or not sel.get("endpoint"):
        print(f"[error] no online agent for skill/agent={skill!r}", file=sys.stderr)
        return 3
    print(f"routing {skill!r} -> {sel.get('agent_key')} @ {sel['endpoint']}")
    resp = _agent_rpc(
        sel["endpoint"],
        "message/send",
        {
            "message": {
                "role": "user",
                "parts": [{"type": "text", "text": args.input}],
                "messageId": str(uuid.uuid4()),
            },
            "metadata": {"skillId": skill},
        },
    )
    if resp.get("error"):
        print(f"[error] {resp['error']}", file=sys.stderr)
        return 4
    result = resp["result"]
    root = result.get("id")
    state = (result.get("status") or {}).get("state")
    delegated = (result.get("metadata") or {}).get("autonomous_delegation")
    print(f"task_id / root_task_id : {root}")
    print(f"state                  : {state}")
    print(f"autonomous_delegation  : {bool(delegated)}")
    print("\ninspect the runtime collaboration graph:")
    print(f"  python scripts/aop.py runtime graph {root}")
    return 0


def cmd_task_inspect(args) -> int:
    task_id = args.task_id
    try:
        graph = _os_get(f"/v1/runtime/graph/{task_id}")
    except httpx.HTTPError as exc:
        print(f"[error] runtime graph lookup failed: {exc}", file=sys.stderr)
        return 5
    print(
        f"task/root {task_id}: edges={graph['edge_count']} max_depth={graph['max_depth']} "
        f"agents={graph['agents']}"
    )
    _print_tree(graph["tree"], _name_map())
    return 0


def cmd_task_events(args) -> int:
    print(json.dumps(_os_get(f"/v1/tasks/{args.task_id}/events"), indent=2, default=str))
    return 0


def cmd_task_execution(args) -> int:
    print(json.dumps(_os_get(f"/v1/tasks/{args.task_id}/execution"), indent=2, default=str))
    return 0


def cmd_task_cancel(args) -> int:
    print(json.dumps(_os_post(f"/v1/tasks/{args.task_id}/cancel"), indent=2, default=str))
    return 0


def cmd_task_recover(args) -> int:
    print(json.dumps(_os_post(f"/v1/tasks/{args.task_id}/recover"), indent=2, default=str))
    return 0


def cmd_task_graph(args) -> int:
    print(json.dumps(_os_get(f"/v1/tasks/{args.task_id}/collaboration-graph"), indent=2, default=str))
    return 0


def cmd_task_cost(args) -> int:
    path = f"/v1/tasks/{args.task_id}/cost"
    if args.breakdown:
        path += "/breakdown"
    print(json.dumps(_os_get(path), indent=2, default=str))
    return 0


def cmd_agent_health(args) -> int:
    try:
        data = _os_get(f"/v1/agents/{args.agent_id}/health")
    except httpx.HTTPError:
        data = _os_get(f"/v1/agent-runtime/{args.agent_id}/health")
    print(json.dumps(data, indent=2, default=str))
    return 0


def cmd_agent_drain(args) -> int:
    try:
        data = _os_post(f"/v1/agents/{args.agent_id}/drain")
    except httpx.HTTPError:
        data = _os_post(f"/v1/agent-runtime/{args.agent_id}/drain")
    print(json.dumps(data, indent=2, default=str))
    return 0


def cmd_agent_reliability(args) -> int:
    print(json.dumps(_os_get(f"/v1/agents/{args.agent_id}/reliability"), indent=2, default=str))
    return 0


def cmd_agent_capacity(args) -> int:
    print(json.dumps(_os_get(f"/v1/agents/{args.agent_id}/capacity"), indent=2, default=str))
    return 0


def cmd_runtime_graph(args) -> int:
    graph = _os_get(f"/v1/runtime/graph/{args.root_task_id}")
    print(f"runtime execution graph  root={args.root_task_id}")
    print(f"  kind={graph['kind']} edges={graph['edge_count']} max_depth={graph['max_depth']}")
    print(f"  agents={graph['agents']}")
    print("  (this is a RUNTIME graph, not a predefined workflow DAG)")
    _print_tree(graph["tree"], _name_map())
    if args.json:
        print(json.dumps(graph, indent=2, ensure_ascii=False))
    return 0


def cmd_scheduling_candidates(args) -> int:
    print(json.dumps(_os_get(f"/v1/scheduling/candidates?skill={args.skill}&limit={args.limit}"), indent=2))
    return 0


def cmd_scheduling_preview(args) -> int:
    body = {"skill": args.skill, "requirement": {"skill": args.skill}, "estimated_cost": args.cost}
    print(json.dumps(_os_post("/v1/scheduling/preview", body), indent=2))
    return 0


def cmd_scheduling_select(args) -> int:
    body = {"skill": args.skill, "requirement": {"skill": args.skill}, "estimated_cost": args.cost}
    print(json.dumps(_os_post("/v1/scheduling/select", body), indent=2))
    return 0


def cmd_tenant_quota(args) -> int:
    print(json.dumps(_os_get(f"/v1/tenants/{args.tenant_id}/quota"), indent=2))
    return 0


def cmd_tenant_budget(args) -> int:
    print(json.dumps(_os_get(f"/v1/tenants/{args.tenant_id}/budget"), indent=2))
    return 0


def _load_manifest_file(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(raw)
        if isinstance(data, dict):
            return data
    except Exception as exc:
        raise SystemExit(f"cannot parse manifest {path}: {exc}") from exc
    raise SystemExit(f"manifest must be JSON or YAML object: {path}")


def cmd_agent_register(args) -> int:
    data = _load_manifest_file(args.manifest)
    try:
        out = _os_post("/v1/marketplace/register", {"manifest": data, "skip_gateway": args.skip_gateway})
    except httpx.HTTPStatusError:
        out = _os_post("/v1/agent-runtime/register", {"manifest": data, "skip_gateway": args.skip_gateway})
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_agent_info(args) -> int:
    agents = _agents()
    for a in agents:
        if args.id in {
            a.get("agent_id"),
            a.get("id"),
            a.get("agent_key"),
            a.get("name"),
        }:
            print(json.dumps(a, indent=2, default=str))
            return 0
    try:
        print(json.dumps(_os_get(f"/v1/marketplace/agents/{args.id}"), indent=2, default=str))
        return 0
    except httpx.HTTPError:
        pass
    print(f"[error] agent not found: {args.id}", file=sys.stderr)
    return 1


def cmd_skill_list(_args) -> int:
    data = _os_get("/v1/skills")
    for s in data.get("skills") or []:
        print(f"  {s.get('name'):<28} v{s.get('version'):<8} providers={len(s.get('providers') or [])}")
    return 0


def cmd_skill_search(args) -> int:
    body = {"skill": args.query, "q": args.query}
    if args.version:
        body["version"] = args.version
    data = _os_post("/v1/skills/search", body)
    print(json.dumps(data, indent=2, default=str))
    return 0


def cmd_skill_get(args) -> int:
    print(json.dumps(_os_get(f"/v1/skills/{args.name}"), indent=2, default=str))
    return 0


def cmd_marketplace_search(args) -> int:
    q = f"?q={args.query}" if args.query else ""
    print(json.dumps(_os_get(f"/v1/marketplace/agents{q}"), indent=2, default=str))
    return 0


def cmd_marketplace_publish(args) -> int:
    data = _load_manifest_file(args.manifest)
    body: dict = {"manifest": data}
    if args.package_id:
        body["package_id"] = args.package_id
    print(json.dumps(_os_post("/v1/marketplace/agents", body), indent=2, default=str))
    return 0


def cmd_marketplace_install(args) -> int:
    print(json.dumps(_os_post(f"/v1/marketplace/agents/{args.agent}/install", {}), indent=2, default=str))
    return 0


def cmd_marketplace_activate(args) -> int:
    print(json.dumps(_os_post(f"/v1/marketplace/agents/{args.agent}/activate", {}), indent=2, default=str))
    return 0


def cmd_marketplace_deactivate(args) -> int:
    print(json.dumps(_os_post(f"/v1/marketplace/agents/{args.agent}/deactivate", {}), indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aop", description="Minimal A2A OS dev CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    ag = sub.add_parser("agent", help="agent registry / discovery")
    agsub = ag.add_subparsers(dest="sub", required=True)
    agsub.add_parser("list").set_defaults(func=cmd_agent_list)
    d = agsub.add_parser("discover")
    d.add_argument("--skill", required=True)
    d.add_argument("--limit", type=int, default=20)
    d.set_defaults(func=cmd_agent_discover)
    ah = agsub.add_parser("health")
    ah.add_argument("agent_id")
    ah.set_defaults(func=cmd_agent_health)
    ad = agsub.add_parser("drain")
    ad.add_argument("agent_id")
    ad.set_defaults(func=cmd_agent_drain)
    ar = agsub.add_parser("reliability")
    ar.add_argument("agent_id")
    ar.set_defaults(func=cmd_agent_reliability)
    ac = agsub.add_parser("capacity")
    ac.add_argument("agent_id")
    ac.set_defaults(func=cmd_agent_capacity)
    areg = agsub.add_parser("register")
    areg.add_argument("manifest", help="path to agent manifest YAML/JSON")
    areg.add_argument("--skip-gateway", action="store_true")
    areg.set_defaults(func=cmd_agent_register)
    ainfo = agsub.add_parser("info")
    ainfo.add_argument("id")
    ainfo.set_defaults(func=cmd_agent_info)

    sk = sub.add_parser("skill", help="skill catalog / discovery")
    sksub = sk.add_subparsers(dest="sub", required=True)
    sksub.add_parser("list").set_defaults(func=cmd_skill_list)
    sks = sksub.add_parser("search")
    sks.add_argument("query")
    sks.add_argument("--version", default=None)
    sks.set_defaults(func=cmd_skill_search)
    skg = sksub.add_parser("get")
    skg.add_argument("name")
    skg.set_defaults(func=cmd_skill_get)

    mp = sub.add_parser("marketplace", help="agent marketplace")
    mpsub = mp.add_subparsers(dest="sub", required=True)
    mps = mpsub.add_parser("search")
    mps.add_argument("query", nargs="?", default=None)
    mps.set_defaults(func=cmd_marketplace_search)
    mpp = mpsub.add_parser("publish")
    mpp.add_argument("manifest")
    mpp.add_argument("--package-id", default=None)
    mpp.set_defaults(func=cmd_marketplace_publish)
    mpi = mpsub.add_parser("install")
    mpi.add_argument("agent", help="package_id")
    mpi.set_defaults(func=cmd_marketplace_install)
    mpa = mpsub.add_parser("activate")
    mpa.add_argument("agent")
    mpa.set_defaults(func=cmd_marketplace_activate)
    mpd = mpsub.add_parser("deactivate")
    mpd.add_argument("agent")
    mpd.set_defaults(func=cmd_marketplace_deactivate)

    tk = sub.add_parser("task")
    tksub = tk.add_subparsers(dest="sub", required=True)
    s = tksub.add_parser("submit")
    s.add_argument("--agent", required=True)
    s.add_argument("--input", required=True)
    s.add_argument("--skill", default=None)
    s.set_defaults(func=cmd_task_submit)
    for name, fn in (
        ("inspect", cmd_task_inspect),
        ("events", cmd_task_events),
        ("execution", cmd_task_execution),
        ("cancel", cmd_task_cancel),
        ("recover", cmd_task_recover),
        ("graph", cmd_task_graph),
    ):
        p_ = tksub.add_parser(name)
        p_.add_argument("task_id")
        p_.set_defaults(func=fn)
    tcost = tksub.add_parser("cost")
    tcost.add_argument("task_id")
    tcost.add_argument("--breakdown", action="store_true")
    tcost.set_defaults(func=cmd_task_cost)

    rt = sub.add_parser("runtime")
    rtsub = rt.add_subparsers(dest="sub", required=True)
    g = rtsub.add_parser("graph")
    g.add_argument("root_task_id")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_runtime_graph)

    sch = sub.add_parser("scheduling")
    schsub = sch.add_subparsers(dest="sub", required=True)
    sc = schsub.add_parser("candidates")
    sc.add_argument("--skill", required=True)
    sc.add_argument("--limit", type=int, default=20)
    sc.set_defaults(func=cmd_scheduling_candidates)
    sp = schsub.add_parser("preview")
    sp.add_argument("--skill", required=True)
    sp.add_argument("--cost", type=float, default=0.1)
    sp.set_defaults(func=cmd_scheduling_preview)
    ss = schsub.add_parser("select")
    ss.add_argument("--skill", required=True)
    ss.add_argument("--cost", type=float, default=0.1)
    ss.set_defaults(func=cmd_scheduling_select)

    tn = sub.add_parser("tenant")
    tnsub = tn.add_subparsers(dest="sub", required=True)
    tq = tnsub.add_parser("quota")
    tq.add_argument("tenant_id")
    tq.set_defaults(func=cmd_tenant_quota)
    tb = tnsub.add_parser("budget")
    tb.add_argument("tenant_id")
    tb.set_defaults(func=cmd_tenant_budget)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except httpx.HTTPError as exc:
        print(f"[error] OS request failed ({OS_URL}): {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
