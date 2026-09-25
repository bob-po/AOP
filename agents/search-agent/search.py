"""Deep-research web search backed by vendored Open Deep Research (A2A payload)."""

from __future__ import annotations

import os
import re
import uuid
from typing import Any
from urllib.parse import quote_plus, urlparse

from page_fetch import enrich_results_with_pages, format_page_summary

USER_AGENT = "AOP-SearchAgent/0.6 (+https://github.com/aop)"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_TECH_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9+./_-]{1,})(?![A-Za-z0-9])"
)
_STOP_TOKENS = {
    "is",
    "the",
    "a",
    "an",
    "to",
    "of",
    "and",
    "or",
    "in",
    "on",
    "for",
    "what",
    "how",
    "ppt",
    "pptx",
    "pdf",
    "doc",
    "docx",
    "html",
    "url",
    "http",
    "https",
    "www",
}

_CJK_STOP = {
    "帮我",
    "请帮",
    "请你",
    "麻烦",
    "一下",
    "一个",
    "一份",
    "一篇",
    "一些",
    "关于",
    "进行",
    "相关",
    "内容",
    "资料",
    "材料",
    "信息",
    "功能",
    "介绍",
    "演示",
    "输出",
    "生成",
    "制作",
    "搜索",
    "检索",
    "查找",
    "查询",
    "调研",
    "了解",
    "报告",
    "文档",
    "幻灯片",
    "课件",
    "给我",
    "为我",
    "需要",
    "希望",
    "可以",
    "怎么",
    "如何",
    "什么",
    "这个",
    "那个",
    "公司",
    "产品",
    "平台",
}

_ENTITY_ALIASES: dict[str, list[str]] = {
    "哔哩哔哩": ["Bilibili", "哔哩哔哩", "bilibili"],
    "哔哩哔哩弹幕网": ["Bilibili", "哔哩哔哩"],
    "B站": ["Bilibili", "哔哩哔哩", "B站"],
    "b站": ["Bilibili", "哔哩哔哩"],
    "抖音": ["Douyin", "抖音", "TikTok China"],
    "微信": ["WeChat", "微信"],
    "阿里巴巴": ["Alibaba", "阿里巴巴"],
    "腾讯": ["Tencent", "腾讯"],
    "百度": ["Baidu", "百度"],
    "字节跳动": ["ByteDance", "字节跳动"],
}

_SERP_JUNK_HOSTS = {
    "www.sogou.com",
    "sogou.com",
    "www.baidu.com",
    "baidu.com",
    "cn.bing.com",
    "www.bing.com",
    "bing.com",
    "www.so.com",
    "so.com",
    "www.google.com",
    "www.google.com.hk",
    "google.com",
    "www.17so.cn",
    "17so.cn",
}

_DICT_JUNK_HOST_SUFFIXES = (
    "hgcha.com",
    "zdic.net",
    "zdict.net",
    "dict.cn",
    "iciba.com",
    "youdao.com",
    "hanyu.baidu.com",
    "xiaohongshu.com",
)

_GOAL_NOISE_RE = re.compile(
    r"("
    r"帮我|请帮我|请你|麻烦你|给我|为我|"
    r"搜索|检索|查找|查询|调研|了解|介绍|生成|制作|输出|写一份|写一篇|"
    r"相关内容|功能介绍|演示|汇报|报告|文档|资料|材料|"
    r"一下|一个|一份|一篇|"
    r"search\s+(for\s+)?|look\s+up|research|"
    r"generate|create|make|write|build|"
    r"\bPPTX?\b|\bPDF\b|幻灯片|课件"
    r")+",
    flags=re.IGNORECASE,
)

_SOURCE_BLOCK_RE = re.compile(
    r"---\s*SOURCE\s+\d+:\s*(.+?)\s*---\s*\nURL:\s*(\S+)",
    flags=re.IGNORECASE,
)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BARE_URL_RE = re.compile(r"https?://[^\s\)\]\"'<>]+")


def extract_search_topic(goal: str) -> str:
    """Reduce a multi-intent user goal to the subject we should actually search."""
    raw = (goal or "").strip()
    if not raw:
        return ""

    entity = _match_known_entity(raw)
    if entity:
        return entity

    tokens = [
        t
        for t in _TECH_TOKEN_RE.findall(raw)
        if len(t) >= 2 and t.lower() not in _STOP_TOKENS
    ]
    scored = sorted(
        tokens,
        key=lambda t: (
            any(c.isdigit() for c in t),
            any(c.isupper() for c in t),
            len(t),
        ),
        reverse=True,
    )
    if scored:
        return " ".join(scored[:3])

    cleaned = _GOAL_NOISE_RE.sub(" ", raw)
    cleaned = re.sub(r"[，,。.!！？?、；;：:\s]+", " ", cleaned).strip()
    cjk_spans = _cjk_subject_spans(cleaned or raw)
    if cjk_spans:
        return cjk_spans[0]
    if cleaned:
        return cleaned[:80]
    return raw[:80]


def _match_known_entity(text: str) -> str | None:
    best = ""
    for name in _ENTITY_ALIASES:
        if name in text and len(name) > len(best):
            best = name
    return best or None


def _cjk_subject_spans(text: str) -> list[str]:
    spans = re.findall(r"[\u4e00-\u9fff]{2,}", text or "")
    kept = [s for s in spans if s not in _CJK_STOP and not all(ch in "的了吗呢吧啊" for ch in s)]
    kept.sort(key=len, reverse=True)
    out: list[str] = []
    seen: set[str] = set()
    for s in kept:
        if s in seen:
            continue
        if any(s in prev for prev in out):
            continue
        seen.add(s)
        out.append(s)
    return out


def topic_keywords(query: str) -> list[str]:
    topic = extract_search_topic(query) or (query or "").strip()
    keys: list[str] = []
    seen: set[str] = set()

    def _add(k: str) -> None:
        k = (k or "").strip()
        if len(k) < 2:
            return
        key = k.casefold()
        if key in seen or k in _CJK_STOP or key in _STOP_TOKENS:
            return
        seen.add(key)
        keys.append(k)

    _add(topic)
    for alias in _ENTITY_ALIASES.get(topic, []):
        _add(alias)
    for name, aliases in _ENTITY_ALIASES.items():
        if topic == name or topic in aliases or topic.casefold() in {a.casefold() for a in aliases}:
            _add(name)
            for a in aliases:
                _add(a)
    for span in _cjk_subject_spans(topic):
        _add(span)
    for t in _TECH_TOKEN_RE.findall(f"{query} {topic}"):
        if len(t) >= 2 and t.lower() not in _STOP_TOKENS:
            _add(t)
    return keys


def search_query_variants(query: str) -> list[str]:
    """Prefer focused topic + English aliases over multi-intent Chinese prose."""
    q = (query or "").strip()
    if not q:
        return []
    topic = extract_search_topic(q)
    variants: list[str] = []
    tokens = [
        t
        for t in _TECH_TOKEN_RE.findall(q)
        if len(t) >= 2 and t.lower() not in _STOP_TOKENS
    ]
    seen: set[str] = set()
    uniq: list[str] = []
    for t in tokens:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)

    q_lower = q.lower()
    agentish = bool(
        re.search(r"agent|协议|協議|protocol|编排|orchestr", q_lower, flags=re.I)
        or _CJK_RE.search(q)
    )
    if any(t.upper() == "A2A" for t in uniq) and agentish:
        variants.extend(
            [
                "What is A2A Agent2Agent protocol",
                "A2A Agent2Agent open protocol Google",
                "Agent2Agent A2A protocol",
            ]
        )

    for key in topic_keywords(q):
        if key.casefold() != (topic or "").casefold():
            variants.append(key)
        aliases = _ENTITY_ALIASES.get(key) or []
        for a in aliases:
            variants.append(a)
            if _CJK_RE.search(a) is None:
                variants.append(f"{a} company overview")
                variants.append(f"What is {a}")

    if topic and topic.casefold() != q.casefold():
        variants.insert(0, topic)
        if _CJK_RE.search(topic):
            variants.append(f"{topic} 公司 简介")
            variants.append(f"{topic} 业务 介绍")
        if _TECH_TOKEN_RE.search(topic):
            variants.append(f"What is {topic}")
            variants.append(f"{topic} features")
            variants.append(f"{topic} 功能介绍")

    if _CJK_RE.search(q) and uniq:
        eng = " ".join(uniq)
        if "protocol" not in eng.lower() and any(t.upper() == "A2A" for t in uniq):
            eng = f"{eng} protocol"
        if not eng.lower().startswith("what"):
            eng = f"What is {eng}"
        variants.append(eng)
        variants.append(" ".join(uniq))

    if not (topic and (_TECH_TOKEN_RE.search(topic) or topic in _ENTITY_ALIASES or _CJK_RE.search(topic))):
        variants.append(q)
    out: list[str] = []
    seen_q: set[str] = set()
    for v in variants:
        if v.strip().upper() == "A2A":
            continue
        key = v.casefold()
        if key in seen_q:
            continue
        seen_q.add(key)
        out.append(v)
    return out or ([topic] if topic else [q])


def _host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""


def _is_dict_or_junk_host(host: str) -> bool:
    if not host:
        return False
    if host in _SERP_JUNK_HOSTS:
        return True
    return any(host == s or host.endswith("." + s) for s in _DICT_JUNK_HOST_SUFFIXES)


def _is_serp_junk(item: dict[str, Any]) -> bool:
    host = _host_of(str(item.get("url") or ""))
    if _is_dict_or_junk_host(host):
        return True
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "")
    blob = f"{title} {snippet}".lower()
    if any(k in blob for k in ("拼音", "组词", "笔画", "笔顺", "康熙字典", "汉语查", "zidian")):
        return True
    try:
        path = (urlparse(str(item.get("url") or "")).path or "").strip("/")
    except Exception:  # noqa: BLE001
        path = ""
    if host.endswith((".com", ".cn", ".hk")) and not path:
        if any(k in title.lower() for k in ("搜索", "search", "必应", "bing", "google", "搜狗", "360")):
            return True
    return False


def _results_relevant(query: str, results: list[dict[str, Any]]) -> bool:
    if not results:
        return False
    cleaned = [r for r in results if not _is_serp_junk(r)]
    if not cleaned:
        return False
    if len(cleaned) < max(1, (len(results) + 1) // 2):
        return False

    keys = [k.lower() for k in topic_keywords(query)]
    ascii_tokens = {
        t.lower()
        for t in _TECH_TOKEN_RE.findall(query)
        if len(t) >= 2 and t.lower() not in _STOP_TOKENS
    }
    for k in keys:
        if re.fullmatch(r"[a-z0-9+./_-]{2,}", k):
            ascii_tokens.add(k)

    q_lower = query.lower()
    want_a2a_protocol = ("a2a" in ascii_tokens) and bool(
        re.search(r"protocol|协议|協議|agent2agent|agent|编排|orchestr", q_lower, flags=re.I)
        or _CJK_RE.search(query)
    )

    hits = 0
    for item in cleaned:
        blob = f"{item.get('title', '')} {item.get('url', '')} {item.get('snippet', '')}".lower()
        if want_a2a_protocol:
            if "agent2agent" in blob or ("a2a" in blob and "protocol" in blob):
                hits += 1
            continue
        if keys and any(tok.lower() in blob for tok in keys):
            hits += 1
        elif ascii_tokens and any(tok in blob for tok in ascii_tokens):
            hits += 1
        elif not keys and not ascii_tokens:
            hits += 1
    if want_a2a_protocol:
        return hits >= 1
    need = max(1, (len(cleaned) + 2) // 3)
    return hits >= need


def filter_relevant_results(query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for item in results or []:
        if _is_serp_junk(item):
            continue
        score = _score_result(query, item)
        if score < 0.25:
            continue
        row = dict(item)
        row["relevance"] = round(score, 3)
        kept.append(row)
    return kept


def _score_result(query: str, item: dict[str, Any]) -> float:
    keys = topic_keywords(query)
    blob = f"{item.get('title', '')} {item.get('url', '')} {item.get('snippet', '')}".lower()
    if not blob.strip():
        return 0.0
    if _is_serp_junk(item):
        return 0.0
    if not keys:
        return 0.2
    hits = sum(1 for tok in keys if tok.lower() in blob)
    if hits == 0:
        return 0.05
    return min(1.0, 0.35 + 0.25 * hits)


def _confidence_for_results(query: str, results: list[dict[str, Any]]) -> float:
    if not results:
        return 0.0
    scores = [float(r.get("relevance") or _score_result(query, r)) for r in results]
    return round(sum(scores) / len(scores), 3)


def mock_results(query: str) -> list[dict[str, Any]]:
    topic = extract_search_topic(query) or query
    q = quote_plus(topic)
    return [
        {
            "title": f"Overview: {topic}",
            "url": f"https://example.com/search?q={q}",
            "snippet": f"High-level introduction and references related to '{topic}'.",
        },
        {
            "title": f"{topic} — features",
            "url": f"https://example.com/features?q={q}",
            "snippet": f"Key capabilities and feature highlights for '{topic}'.",
        },
        {
            "title": f"{topic} — notes",
            "url": f"https://example.com/notes?q={q}",
            "snippet": f"Background notes and further reading about '{topic}'.",
        },
    ]


def _no_relevant_payload(
    query: str,
    *,
    tried: list[str],
    reason: str,
) -> dict[str, Any]:
    summary = (
        f"No relevant results for: {query}\n"
        f"Status: no_relevant_results\n"
        f"Tried: {', '.join(tried) or '(none)'}\n"
        f"Reason: {reason}\n\n"
        "Refusing to forward empty or irrelevant research to downstream nodes."
    )
    return {
        "query": query,
        "source": "none",
        "status": "no_relevant_results",
        "confidence": 0.0,
        "results": [],
        "tried": list(tried),
        "answer": "",
        "summary": summary,
        "error": reason,
    }


def _error_payload(query: str, *, tried: list[str], reason: str) -> dict[str, Any]:
    return {
        "query": query,
        "source": "open-deep-research",
        "status": "error",
        "confidence": 0.0,
        "results": [],
        "tried": list(tried),
        "answer": "",
        "summary": f"Deep research failed for: {query}\nError: {reason}",
        "error": reason,
    }


def _research_configurable() -> dict[str, Any]:
    """Build LangGraph configurable overrides from env."""
    cfg: dict[str, Any] = {
        "thread_id": str(uuid.uuid4()),
        "allow_clarification": False,
    }
    search_api = (os.getenv("SEARCH_API") or os.getenv("ODR_SEARCH_API") or "tavily").strip().lower()
    if search_api:
        cfg["search_api"] = search_api

    for env_key, cfg_key in (
        ("ODR_RESEARCH_MODEL", "research_model"),
        ("ODR_SUMMARIZATION_MODEL", "summarization_model"),
        ("ODR_COMPRESSION_MODEL", "compression_model"),
        ("ODR_FINAL_REPORT_MODEL", "final_report_model"),
    ):
        val = (os.getenv(env_key) or "").strip()
        if val:
            cfg[cfg_key] = val

    for env_key, cfg_key, cast in (
        ("ODR_MAX_CONCURRENT", "max_concurrent_research_units", int),
        ("ODR_MAX_ITERATIONS", "max_researcher_iterations", int),
        ("ODR_MAX_TOOL_CALLS", "max_react_tool_calls", int),
    ):
        raw = (os.getenv(env_key) or "").strip()
        if not raw:
            continue
        try:
            cfg[cfg_key] = cast(raw)
        except ValueError:
            pass
    return cfg


def _parse_sources(*blobs: str, limit: int = 12) -> list[dict[str, Any]]:
    """Extract structured citations from report / raw notes text."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []

    def _add(title: str, url: str, snippet: str = "") -> None:
        url = (url or "").rstrip(".,;")
        if not url.startswith("http") or url in seen:
            return
        if _is_dict_or_junk_host(_host_of(url)):
            return
        seen.add(url)
        out.append(
            {
                "title": (title or url).strip()[:200] or url,
                "url": url,
                "snippet": (snippet or title or "")[:400],
            }
        )

    text = "\n".join(b for b in blobs if b)
    for title, url in _SOURCE_BLOCK_RE.findall(text):
        _add(title.strip(), url.strip())
        if len(out) >= limit:
            return out

    for title, url in _MD_LINK_RE.findall(text):
        _add(title.strip(), url.strip())
        if len(out) >= limit:
            return out

    for url in _BARE_URL_RE.findall(text):
        _add(url, url)
        if len(out) >= limit:
            break
    return out


def _notes_text(raw_notes: Any) -> str:
    if not raw_notes:
        return ""
    if isinstance(raw_notes, str):
        return raw_notes
    if isinstance(raw_notes, list):
        return "\n".join(str(x) for x in raw_notes if x)
    return str(raw_notes)


async def run_deep_research(query: str, *, limit: int = 8) -> dict[str, Any]:
    """Invoke Open Deep Research and map to the A2A search payload contract."""
    from langchain_core.messages import HumanMessage

    from deep_research.deep_researcher import deep_researcher

    tried = ["open-deep-research"]
    topic = extract_search_topic(query) or (query or "").strip()
    config = {"configurable": _research_configurable()}

    try:
        result = await deep_researcher.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config=config,
        )
    except Exception as exc:  # noqa: BLE001
        return _error_payload(topic or query, tried=tried, reason=str(exc)[:500])

    final_report = str(result.get("final_report") or "").strip()
    research_brief = str(result.get("research_brief") or "").strip()
    notes = _notes_text(result.get("raw_notes"))

    if final_report.lower().startswith("error generating final report"):
        return _error_payload(topic or query, tried=tried, reason=final_report[:500])

    results = _parse_sources(final_report, notes, limit=limit)
    results = filter_relevant_results(query, results) or results
    if results and (os.getenv("SEARCH_FETCH_PAGES") or "0").strip() not in {"0", "false", "no"}:
        results = enrich_results_with_pages(results)

    if not final_report and not results:
        return _no_relevant_payload(
            topic or query,
            tried=tried,
            reason="deep research returned empty report and no sources",
        )

    confidence = 0.85 if results else 0.6
    if results:
        confidence = max(confidence, _confidence_for_results(query, results))

    summary_lines = [
        f"Search results for: {topic or query}",
        "Source: open-deep-research",
        "Status: ok",
        f"Confidence: {confidence:.2f}",
        "",
    ]
    if research_brief:
        summary_lines.append(f"Research brief: {research_brief[:500]}")
        summary_lines.append("")
    if final_report:
        summary_lines.append(final_report)
        summary_lines.append("")
    for i, item in enumerate(results, 1):
        summary_lines.append(f"{i}. {item['title']}")
        summary_lines.append(f"   {item['url']}")
        if item.get("snippet"):
            summary_lines.append(f"   {item['snippet']}")
        summary_lines.append("")
    page_lines = format_page_summary(results)
    if page_lines:
        summary_lines.append("---")
        summary_lines.append("")
        summary_lines.extend(page_lines)

    return {
        "query": topic or query,
        "goal_query": query,
        "source": "open-deep-research",
        "status": "ok",
        "confidence": round(confidence, 3),
        "results": results,
        "tried": tried,
        "answer": final_report,
        "research_brief": research_brief,
        "summary": "\n".join(summary_lines).strip(),
    }


async def run_search(query: str) -> dict[str, Any]:
    """A2A search entrypoint.

    Modes (`SEARCH_MODE`):
      - ``mock``: deterministic offline results (tests / no keys)
      - ``auto`` / ``live`` / ``research``: Open Deep Research (Tavily + LLM)
    """
    mode = (os.getenv("SEARCH_MODE") or "auto").strip().lower()
    limit = int(os.getenv("SEARCH_LIMIT") or "8")
    allow_mock = (os.getenv("SEARCH_ALLOW_MOCK_FALLBACK") or "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    topic = extract_search_topic(query) or (query or "").strip()
    tried: list[str] = []

    if mode == "mock":
        results = mock_results(topic or query)
        summary_lines = [
            f"Search results for: {topic or query}",
            "Source: mock",
            "Status: ok",
            "Confidence: 0.50",
            "",
        ]
        for i, item in enumerate(results, 1):
            summary_lines.append(f"{i}. {item['title']}")
            summary_lines.append(f"   {item['url']}")
            if item.get("snippet"):
                summary_lines.append(f"   {item['snippet']}")
            summary_lines.append("")
        return {
            "query": topic or query,
            "goal_query": query,
            "source": "mock",
            "status": "ok",
            "confidence": 0.5,
            "results": results,
            "tried": ["mock"],
            "summary": "\n".join(summary_lines).strip(),
        }

    payload = await run_deep_research(query, limit=limit)
    tried.extend(payload.get("tried") or ["open-deep-research"])

    if payload.get("status") == "ok":
        return payload

    if allow_mock:
        results = mock_results(topic or query)
        return {
            "query": topic or query,
            "goal_query": query,
            "source": "mock-fallback",
            "status": "ok",
            "confidence": 0.35,
            "results": results,
            "tried": tried + ["mock-fallback"],
            "answer": payload.get("answer") or "",
            "summary": (
                f"Search results for: {topic or query}\n"
                f"Source: mock-fallback\n"
                f"(deep research failed: {payload.get('error') or payload.get('status')})\n\n"
                + "\n".join(f"- {r['title']}: {r['url']}" for r in results)
            ),
            "error": payload.get("error"),
        }

    return payload
