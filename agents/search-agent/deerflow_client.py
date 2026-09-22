"""DeerFlow (bytedance/deer-flow 1.x) research backend client.

Calls ``POST /api/chat/stream`` and maps SSE events into the search-agent
payload shape: ``{query, source, results, answer, summary, tried}``.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx

USER_AGENT = "AOP-SearchAgent/0.5 (+deerflow)"

_LAST_ERROR = ""


def last_error() -> str:
    return _LAST_ERROR


def _set_error(msg: str) -> None:
    global _LAST_ERROR
    _LAST_ERROR = (msg or "")[:500]


def _base_url() -> str:
    raw = (os.getenv("DEERFLOW_URL") or "").strip().rstrip("/")
    return raw


def _timeout() -> float:
    try:
        return float(os.getenv("DEERFLOW_TIMEOUT") or "300")
    except ValueError:
        return 300.0


def _max_search_results(limit: int) -> int:
    env = os.getenv("DEERFLOW_MAX_SEARCH_RESULTS")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    return max(1, min(limit, 10))


def _citation_to_result(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    url = (item.get("url") or meta.get("url") or "").strip()
    title = (item.get("title") or meta.get("title") or "").strip()
    snippet = (
        item.get("content")
        or item.get("cited_text")
        or item.get("snippet")
        or meta.get("content")
        or meta.get("snippet")
        or ""
    )
    snippet = str(snippet).strip()
    if not url:
        return None
    if not title:
        title = urlparse(url).netloc or url
    return {"title": title[:200], "url": url, "snippet": snippet[:400]}


def _parse_tool_content(content: str, *, limit: int) -> list[dict[str, str]]:
    """Best-effort parse of DeerFlow ``tool_call_result.content``."""
    text = (content or "").strip()
    if not text:
        return []

    data: Any = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Some tools wrap JSON in prose; try to locate a JSON array/object.
        for match in re.finditer(r"(\[[\s\S]*\]|\{[\s\S]*\})", text):
            try:
                data = json.loads(match.group(1))
                break
            except json.JSONDecodeError:
                continue

    results: list[dict[str, str]] = []
    if isinstance(data, list):
        for item in data:
            mapped = _citation_to_result(item)
            if mapped:
                results.append(mapped)
            if len(results) >= limit:
                break
    elif isinstance(data, dict):
        # Tavily-style: {"results": [...]} or a single hit
        if isinstance(data.get("results"), list):
            for item in data["results"]:
                mapped = _citation_to_result(item)
                if mapped:
                    results.append(mapped)
                if len(results) >= limit:
                    break
        else:
            mapped = _citation_to_result(data)
            if mapped:
                results.append(mapped)

    if results:
        return results

    # Fallback: markdown links in the tool blob / report chunk
    for title, url in re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", text):
        results.append({"title": title[:200], "url": url, "snippet": ""})
        if len(results) >= limit:
            break
    return results


def _dedupe_results(items: list[dict[str, str]], *, limit: int) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in items:
        url = item.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _parse_sse_block(block: str) -> tuple[str | None, dict[str, Any] | None]:
    event_name: str | None = None
    data_lines: list[str] = []
    for line in block.splitlines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if not data_lines:
        return event_name, None
    raw = "\n".join(data_lines).strip()
    if not raw or raw == "[DONE]":
        return event_name, None
    try:
        return event_name, json.loads(raw)
    except json.JSONDecodeError:
        return event_name, None


async def deerflow_search(query: str, *, limit: int = 5) -> dict[str, Any] | None:
    """Run a DeerFlow research stream and map it to search-agent results.

    Returns ``None`` when ``DEERFLOW_URL`` is unset or the call fails, so
    ``run_search`` can fall back to other backends.
    """
    base = _base_url()
    if not base:
        _set_error("DEERFLOW_URL not set")
        return None
    _set_error("")

    max_results = _max_search_results(limit)
    max_steps = int(os.getenv("DEERFLOW_MAX_STEP_NUM") or "3")
    report_style = (os.getenv("DEERFLOW_REPORT_STYLE") or "academic").strip() or "academic"
    # DeerFlow 1.x enum is lowercase (academic / popular_science / ...).
    report_style = report_style.lower().replace("-", "_")
    locale = (os.getenv("DEERFLOW_LOCALE") or "zh-CN").strip() or "zh-CN"
    thread_id = f"aop-{uuid.uuid4().hex[:12]}"

    body = {
        "messages": [{"role": "user", "content": query}],
        "thread_id": thread_id,
        "max_plan_iterations": 1,
        "max_step_num": max_steps,
        "max_search_results": max_results,
        "auto_accepted_plan": True,
        "enable_background_investigation": True,
        "enable_web_search": True,
        "enable_deep_thinking": False,
        "enable_clarification": False,
        "report_style": report_style,
        "locale": locale,
    }

    answer_parts: list[str] = []
    collected: list[dict[str, str]] = []
    endpoint = f"{base}/api/chat/stream"

    try:
        timeout = httpx.Timeout(_timeout(), connect=15.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async with client.stream(
                "POST",
                endpoint,
                json=body,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/event-stream",
                    "Content-Type": "application/json",
                },
            ) as resp:
                if resp.status_code >= 400:
                    body = ""
                    try:
                        body = (await resp.aread()).decode("utf-8", errors="replace")[:300]
                    except Exception:  # noqa: BLE001
                        pass
                    _set_error(f"HTTP {resp.status_code}: {body}")
                    return None
                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        block, buffer = buffer.split("\n\n", 1)
                        event_name, data = _parse_sse_block(block)
                        if not data:
                            continue
                        if event_name == "error":
                            reason = str(data.get("reason") or data.get("error") or "")
                            if reason == "cancelled":
                                continue
                            _set_error(reason or "stream error")
                            return None
                        if event_name == "citations":
                            for c in data.get("citations") or []:
                                mapped = _citation_to_result(c)
                                if mapped:
                                    collected.append(mapped)
                        elif event_name == "tool_call_result":
                            collected.extend(
                                _parse_tool_content(
                                    str(data.get("content") or ""),
                                    limit=max_results * 2,
                                )
                            )
                        elif event_name == "message_chunk":
                            agent = str(data.get("agent") or data.get("langgraph_node") or "")
                            content = data.get("content")
                            if isinstance(content, str) and content:
                                # Prefer reporter / final answer tokens; still keep
                                # researcher prose when reporter is silent.
                                if agent in ("reporter", "researcher", "coder", "planner") or not agent:
                                    if agent == "reporter" or agent == "":
                                        answer_parts.append(content)
                                    elif agent == "researcher" and not answer_parts:
                                        answer_parts.append(content)
                # Flush trailing block without trailing blank line
                if buffer.strip():
                    event_name, data = _parse_sse_block(buffer)
                    if data and event_name == "citations":
                        for c in data.get("citations") or []:
                            mapped = _citation_to_result(c)
                            if mapped:
                                collected.append(mapped)
                    elif data and event_name == "tool_call_result":
                        collected.extend(
                            _parse_tool_content(
                                str(data.get("content") or ""),
                                limit=max_results * 2,
                            )
                        )
                    elif data and event_name == "message_chunk":
                        content = data.get("content")
                        if isinstance(content, str) and content:
                            answer_parts.append(content)
    except Exception as exc:  # noqa: BLE001
        _set_error(f"{type(exc).__name__}: {exc}")
        return None

    answer = "".join(answer_parts).strip()
    results = _dedupe_results(collected, limit=limit)

    # Last resort: pull markdown links out of the report itself
    if not results and answer:
        results = _dedupe_results(
            _parse_tool_content(answer, limit=limit),
            limit=limit,
        )

    if not results and not answer:
        if not _LAST_ERROR:
            _set_error("empty stream (check DeerFlow LLM api_key in conf.yaml / OPENAI_API_KEY)")
        return None

    if not results:
        # Still useful: synthesized research answer without discrete URLs
        results = [
            {
                "title": f"DeerFlow report: {query[:80]}",
                "url": f"{base}/",
                "snippet": answer[:400],
            }
        ]

    summary_lines = [
        f"Search results for: {query}",
        "Source: deerflow",
        "",
    ]
    if answer:
        summary_lines.append(answer)
        summary_lines.append("")
    for i, item in enumerate(results, 1):
        summary_lines.append(f"{i}. {item['title']}")
        summary_lines.append(f"   {item['url']}")
        if item.get("snippet"):
            summary_lines.append(f"   {item['snippet']}")
        summary_lines.append("")

    return {
        "query": query,
        "source": "deerflow",
        "results": results,
        "answer": answer,
        "tried": ["deerflow"],
        "summary": "\n".join(summary_lines).strip(),
    }
