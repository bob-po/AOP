"""Code Agent — sandboxed Python expression evaluator (Phase 27).

Default mode runs a restricted AST interpreter (no imports, no attribute
calls on builtins, no file I/O). Real subprocess/exec is never used.
"""

from __future__ import annotations

import ast
import json
import math
import operator
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parent
CARD_PATH = ROOT / "agent-card.json"
app = FastAPI(title="AOP Code Agent", version="0.1.0")
_TASKS: dict[str, dict[str, Any]] = {}

_SAFE_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_SAFE_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Not: operator.not_}
_SAFE_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_SAFE_FUNCS: dict[str, Any] = {
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "round": round,
    "sorted": sorted,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "range": range,
    "sqrt": math.sqrt,
    "log": math.log,
    "sin": math.sin,
    "cos": math.cos,
}


class SafeEvalError(ValueError):
    pass


class SafeEvaluator(ast.NodeVisitor):
    def visit(self, node: ast.AST) -> Any:  # type: ignore[override]
        method = f"visit_{type(node).__name__}"
        visitor = getattr(self, method, None)
        if visitor is None:
            raise SafeEvalError(f"disallowed syntax: {type(node).__name__}")
        return visitor(node)

    def visit_Module(self, node: ast.Module) -> Any:
        if len(node.body) != 1:
            raise SafeEvalError("only a single expression is allowed")
        return self.visit(node.body[0])

    def visit_Expr(self, node: ast.Expr) -> Any:
        return self.visit(node.value)

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Any:
        if isinstance(node.value, (int, float, str, bool, type(None))):
            return node.value
        raise SafeEvalError("unsupported constant")

    def visit_List(self, node: ast.List) -> list[Any]:
        return [self.visit(elt) for elt in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> tuple[Any, ...]:
        return tuple(self.visit(elt) for elt in node.elts)

    def visit_Dict(self, node: ast.Dict) -> dict[Any, Any]:
        return {
            self.visit(k): self.visit(v)
            for k, v in zip(node.keys, node.values)
            if k is not None
        }

    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in _SAFE_FUNCS:
            return _SAFE_FUNCS[node.id]
        if node.id in {"True", "False", "None"}:
            return {"True": True, "False": False, "None": None}[node.id]
        raise SafeEvalError(f"unknown name: {node.id}")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        op = _SAFE_BINOPS.get(type(node.op))
        if not op:
            raise SafeEvalError("disallowed operator")
        return op(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        op = _SAFE_UNARY.get(type(node.op))
        if not op:
            raise SafeEvalError("disallowed unary")
        return op(self.visit(node.operand))

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        for op_node, comparator in zip(node.ops, node.comparators):
            op = _SAFE_CMP.get(type(op_node))
            if not op:
                raise SafeEvalError("disallowed compare")
            right = self.visit(comparator)
            if not op(left, right):
                return False
            left = right
        return True

    def visit_Call(self, node: ast.Call) -> Any:
        if not isinstance(node.func, ast.Name):
            raise SafeEvalError("only direct function calls allowed")
        fn = _SAFE_FUNCS.get(node.func.id)
        if fn is None:
            raise SafeEvalError(f"function not allowed: {node.func.id}")
        args = [self.visit(a) for a in node.args]
        kwargs = {kw.arg: self.visit(kw.value) for kw in node.keywords if kw.arg}
        return fn(*args, **kwargs)

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)


def safe_eval(source: str) -> Any:
    src = (source or "").strip()
    if not src:
        raise SafeEvalError("empty expression")
    if len(src) > int(os.getenv("CODE_MAX_CHARS", "4000")):
        raise SafeEvalError("expression too long")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as exc:
        raise SafeEvalError(f"syntax error: {exc.msg}") from exc
    return SafeEvaluator().visit(tree)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_card() -> dict[str, Any]:
    card = json.loads(CARD_PATH.read_text(encoding="utf-8"))
    override = os.getenv("AGENT_URL")
    if override:
        card["url"] = override if override.endswith("/") else f"{override}/"
    return card


def _extract_query(params: dict[str, Any]) -> str:
    message = params.get("message") or {}
    parts = message.get("parts") or []
    texts = [p.get("text", "").strip() for p in parts if p.get("type") == "text" and p.get("text")]
    if texts:
        return " ".join(texts).strip()
    raise ValueError("message.parts must include at least one text part")


def run_code(expr: str) -> dict[str, Any]:
    try:
        value = safe_eval(expr)
        return {
            "ok": True,
            "expression": expr,
            "result": value,
            "result_repr": repr(value),
            "sandbox": "ast-safe",
            "note": "Restricted AST eval only — no imports, files, or network.",
        }
    except SafeEvalError as exc:
        return {
            "ok": False,
            "expression": expr,
            "error": str(exc),
            "sandbox": "ast-safe",
        }


def _completed_task(task_id: str, expr: str, payload: dict[str, Any]) -> dict[str, Any]:
    text = (
        payload.get("result_repr")
        if payload.get("ok")
        else f"error: {payload.get('error')}"
    )
    task = {
        "id": task_id,
        "contextId": task_id,
        "status": {"state": "completed", "timestamp": _utc_now()},
        "artifacts": [
            {
                "artifactId": str(uuid.uuid4()),
                "name": "code-result",
                "description": "Sandboxed evaluation result",
                "parts": [{"type": "text", "text": str(text)}],
            },
            {
                "artifactId": str(uuid.uuid4()),
                "name": "code-meta",
                "parts": [{"type": "data", "data": payload}],
            },
        ],
        "metadata": {"skillId": "code-execution", "expression": expr},
    }
    _TASKS[task_id] = task
    return task


@app.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "agent": "code-agent",
        "sandbox": "ast-safe",
        "seccomp_profile": os.getenv("AOP_SECCOMP_PROFILE", "code-agent"),
    }


@app.get("/.well-known/agent-card.json")
@app.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    return JSONResponse(load_card(), media_type="application/json")


@app.post("/")
@app.post("/a2a")
async def a2a_rpc(request: Request) -> JSONResponse:
    body = await request.json()
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}
    try:
        if method == "message/send":
            expr = _extract_query(params)
            payload = run_code(expr)
            result = _completed_task(str(uuid.uuid4()), expr, payload)
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": result})
        if method == "tasks/get":
            task = _TASKS.get(params.get("id"))
            if not task:
                return JSONResponse(
                    {
                        "jsonrpc": "2.0",
                        "id": req_id,
                        "error": {"code": -32001, "message": "Task not found"},
                    }
                )
            return JSONResponse({"jsonrpc": "2.0", "id": req_id, "result": task})
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }
        )
    except ValueError as exc:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": str(exc)},
            }
        )
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": f"Internal error: {exc}"},
            }
        )


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8007"))
    uvicorn.run("agent:app", host="0.0.0.0", port=port, reload=False)
