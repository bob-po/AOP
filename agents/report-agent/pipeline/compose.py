"""Plan a report, then emit HTML/CSS and chart/diagram assets.

The model may supply section text and numeric chart specs. It does not supply
HTML, CSS, or executable code. Markup is escaped and passed through the sandbox
sanitizer before a PDF renderer is allowed to see it.
"""

from __future__ import annotations

import html
import re
from typing import Any

from context import (
    extract_urls,
    format_upstream,
    llm_available,
    llm_chat,
    parse_json_lenient,
)

from pipeline.sandbox import render_pdf, sanitize_markup

_METRIC = re.compile(
    r"(?P<label>[A-Za-z0-9_\-]{0,24})?\s*(?P<name>PSNR|SSIM|LPIPS)\s*[:=]?\s*(?P<value>-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def build_report(
    goal: str,
    upstream: dict[str, str],
    *,
    skill: str = "report-generation",
) -> dict[str, Any]:
    notes = _research_notes(upstream)
    experimental = _is_experimental(goal, notes)
    plan = _layout_plan(goal, experimental)
    plan = _fill_content(plan, goal, notes)
    plan = _merge_llm(plan, goal, notes)
    citations = _citations(notes)
    for label in plan.get("references") or []:
        if any(item.get("source") == label for item in citations):
            continue
        citations.append({"index": str(len(citations) + 1), "url": "", "source": label})
    chart_files = _charts(plan, notes)
    diagram = _outline_svg(plan)
    html_doc, css = _render_html(plan, citations, chart_files, diagram)
    html_doc = sanitize_markup(html_doc)
    css = sanitize_markup(css)

    files: dict[str, Any] = {
        "report.html": html_doc,
        "report.css": css,
        "assets/diagrams/outline.svg": diagram,
    }
    for name, svg in chart_files.items():
        files[f"assets/charts/{name}.svg"] = svg

    pdf = (
        render_pdf({k: v for k, v in files.items() if isinstance(v, str)})
        if skill in {"report-generation", "pdf"}
        else {"engine": "none", "sandbox": "subprocess-workdir", "reason": "skill does not request pdf"}
    )
    if pdf.get("bytes"):
        files["report.pdf"] = {
            "encoding": "base64",
            "content": pdf["bytes"],
            "mime": "application/pdf",
        }

    return {
        "query": goal,
        "format": "html",
        "skill": skill,
        "content": _summary(plan, citations, pdf),
        "plan": plan,
        "citations": citations,
        "files": files,
        "pdf": {k: v for k, v in pdf.items() if k != "bytes"},
        "sandbox": {
            "markup": "escaped+stripped",
            "render": pdf.get("sandbox") or "subprocess-workdir",
            "engine": pdf.get("engine"),
        },
        "stages": [
            "research",
            "analysis",
            "content",
            "charts",
            "citations",
            "layout",
            "html",
            "pdf",
        ],
        "directories": ["assets/images", "assets/charts", "assets/diagrams"],
    }


def _research_notes(upstream: dict[str, str]) -> list[dict[str, str]]:
    notes = []
    for node_id, body in upstream.items():
        text = (body or "").strip()
        if not text:
            continue
        notes.append({"node_id": node_id, "bucket": _bucket(node_id), "text": text[:8000]})
    return notes


def _bucket(node_id: str) -> str:
    name = node_id.lower()
    if any(token in name for token in ("analy", "分析")):
        return "analysis"
    if any(token in name for token in ("method", "方法")):
        return "method"
    if any(token in name for token in ("rag", "knowledge", "背景")):
        return "background"
    if any(token in name for token in ("result", "结果", "metric")):
        return "results"
    return "findings"


def _is_experimental(goal: str, notes: list[dict[str, str]]) -> bool:
    blob = goal + "\n" + "\n".join(note["text"] for note in notes)
    return re.search(r"实验|PSNR|SSIM|LPIPS", blob, re.IGNORECASE) is not None


def _is_brief_goal(goal: str) -> bool:
    """One-sentence / short-answer goals get a 2-section layout."""
    text = (goal or "").strip()
    if not text:
        return False
    if any(k in text for k in ("分析", "对比", "比较", "研究", "调研", "报告", "实验")):
        return False
    markers = ("一句话", "是什么", "什么是", "简述", "简短", "简单介绍")
    if any(k in text for k in markers):
        return True
    compact = re.sub(r"\s+", "", text)
    if len(compact) > 28:
        return False
    return bool(re.search(r"(什么|吗|呢|\?|？)$", compact) or "什么" in compact)


def _layout_plan(goal: str, experimental: bool) -> dict[str, Any]:
    if experimental:
        sections = [
            {"id": "summary", "number": "1", "title": "摘要", "paragraphs": []},
            {"id": "background", "number": "2", "title": "实验背景", "paragraphs": []},
            {"id": "method", "number": "3", "title": "实验方法", "paragraphs": []},
            {
                "id": "results",
                "number": "4",
                "title": "实验结果",
                "paragraphs": [],
                "children": [
                    {"id": "psnr", "number": "4.1", "title": "PSNR", "paragraphs": [], "chart": "psnr"},
                    {"id": "ssim", "number": "4.2", "title": "SSIM", "paragraphs": [], "chart": "ssim"},
                    {"id": "lpips", "number": "4.3", "title": "LPIPS", "paragraphs": [], "chart": "lpips"},
                    {"id": "compare", "number": "4.4", "title": "对比图", "paragraphs": [], "chart": "compare"},
                ],
            },
            {"id": "analysis", "number": "5", "title": "分析", "paragraphs": []},
            {"id": "conclusion", "number": "6", "title": "结论", "paragraphs": []},
            {"id": "references", "number": "7", "title": "References", "paragraphs": []},
        ]
    elif _is_brief_goal(goal):
        sections = [
            {"id": "summary", "number": "1", "title": "摘要", "paragraphs": []},
            {"id": "references", "number": "2", "title": "References", "paragraphs": []},
        ]
    else:
        sections = [
            {"id": "summary", "number": "1", "title": "摘要", "paragraphs": []},
            {"id": "background", "number": "2", "title": "背景", "paragraphs": []},
            {"id": "findings", "number": "3", "title": "研究发现", "paragraphs": []},
            {"id": "analysis", "number": "4", "title": "分析", "paragraphs": []},
            {"id": "conclusion", "number": "5", "title": "结论", "paragraphs": []},
            {"id": "references", "number": "6", "title": "References", "paragraphs": []},
        ]
    return {
        "title": _headline(goal),
        "experimental": experimental,
        "brief": _is_brief_goal(goal) and not experimental,
        "sections": sections,
        "references": [],
    }


def _headline(goal: str) -> str:
    text = re.sub(r"^(请|帮我|帮忙)", "", (goal or "").strip())
    text = re.sub(r"[，,].*$", "", text).strip()
    text = re.sub(r"(搜索资料|输出报告|写一份报告|生成报告).*$", "", text).strip(" ，,。")
    text = re.sub(
        r"^(调研一下|研究一下|了解一下|介绍一下|分析一下|看一下|查一下)",
        "",
        text,
    ).strip()
    if text.startswith("什么是") and not text.startswith("什么是 "):
        text = "什么是 " + text[len("什么是") :].strip()

    def _cap(match: re.Match[str]) -> str:
        word = match.group(0)
        if word.isupper() or word[:1].isupper():
            return word
        return word[:1].upper() + word[1:]

    text = re.sub(r"\b[A-Za-z][A-Za-z0-9_-]*\b", _cap, text)
    if not text:
        text = (goal or "调研报告").strip()
    if len(text) > 28:
        text = text[:28].rstrip("，, ") + "…"
    return text or "调研报告"


def _clip(text: str, limit: int = 700) -> str:
    cleaned = re.sub(r"<[^>]+>", "", text or "")
    cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)
    lines = []
    for line in cleaned.splitlines():
        line = line.strip()
        if not line or line.startswith("http"):
            continue
        lines.append(line)
    blob = " ".join(lines)
    return blob[:limit]


def _fill_content(plan: dict[str, Any], goal: str, notes: list[dict[str, str]]) -> dict[str, Any]:
    by_id = {section["id"]: section for section in _walk(plan["sections"])}
    grouped: dict[str, list[str]] = {}
    for note in notes:
        clipped = _clip(note["text"])
        if clipped:
            grouped.setdefault(note["bucket"], []).append(clipped)
    findings = grouped.get("findings") or []
    background = grouped.get("background") or []
    analysis = grouped.get("analysis") or []

    brief = bool(plan.get("brief"))
    if brief and "summary" in by_id:
        # One or two sentences answering the goal — no multi-section expansion.
        pieces = []
        for item in findings[:1] + analysis[:1] + background[:1]:
            if item and item not in pieces:
                pieces.append(item.rstrip("。"))
        if pieces:
            by_id["summary"]["paragraphs"] = [_clip("。".join(pieces[:2]) + "。", 400)]
        else:
            by_id["summary"]["paragraphs"] = [
                _clip(next((n["text"] for n in notes if n.get("text")), goal), 400)
            ]
        for section in _walk(plan["sections"]):
            section["_fallback"] = list(section.get("paragraphs") or [])
        return plan

    if "findings" in by_id:
        by_id["findings"]["paragraphs"] = findings[:2] or ["上游没有单独的检索结果。"]
    if "background" in by_id:
        by_id["background"]["paragraphs"] = background[:2] or [
            "背景信息不足，以下内容仅基于已给出的上游结果。"
        ]
    if "method" in by_id:
        by_id["method"]["paragraphs"] = (grouped.get("method") or ["方法描述见上游实验记录。"])[:2]
    if "results" in by_id:
        by_id["results"]["paragraphs"] = (grouped.get("results") or ["结果见下列指标。"])[:2]
    if "analysis" in by_id:
        by_id["analysis"]["paragraphs"] = analysis[:2] or ["上游没有单独的分析结论。"]
    finding_text = findings[:2]
    if "findings" in by_id:
        by_id["findings"]["paragraphs"] = finding_text or ["上游没有单独的检索结果。"]
    pieces = []
    for item in finding_text[:1] + analysis[:1] + background[:1]:
        if item not in pieces:
            pieces.append(item.rstrip("。"))
    if "summary" in by_id:
        if pieces:
            by_id["summary"]["paragraphs"] = ["。".join(pieces[:2]) + "。"]
        else:
            by_id["summary"]["paragraphs"] = ["上游结果较少，以下只整理已经给出的材料。"]
    if "conclusion" in by_id:
        closing = (analysis or finding_text or background or ["上游材料还不够形成进一步判断。"])[0]
        if not str(closing).startswith("因此"):
            closing = "因此，" + closing
        by_id["conclusion"]["paragraphs"] = [_clip(closing, 280)]
    for section in _walk(plan["sections"]):
        section["_fallback"] = list(section.get("paragraphs") or [])
    return plan


def _merge_llm(plan: dict[str, Any], goal: str, notes: list[dict[str, str]]) -> dict[str, Any]:
    """Replace paragraph text when the model returns a validated JSON plan.

    Chart specs are accepted only as numbers and short labels. HTML and code
    fields are ignored.
    """
    if not llm_available() or not notes:
        return _scrub(plan, goal)
    brief = bool(plan.get("brief"))
    if brief:
        system = (
            "You write a one-or-two sentence answer to the user's goal. "
            "Return one JSON object with title (short headline), "
            "sections (array of {id, paragraphs} for ids summary and optionally references), "
            "and references (array of source names). "
            "Put the direct answer only in 摘要/summary paragraphs (1-2 plain sentences). "
            "Do not invent background, findings, or analysis sections. "
            "Do not return HTML or code. Ground the answer in the upstream notes."
        )
    else:
        system = (
            "You write the prose of a research report. Return one JSON object with "
            "title (a short headline, never the user's instruction), "
            "sections (array of {id, paragraphs}), and references (array of source names). "
            "paragraphs are plain text in the same language as the goal, 1 to 3 items each. "
            "Do not return HTML, CSS, or code. Do not copy the user goal into a paragraph. "
            "Do not repeat a section title as a paragraph. "
            "Keep 摘要, 研究发现, and 分析 distinct. Ground every sentence in the upstream notes."
        )
    user = f"Goal: {goal}\n\nExisting section ids: {[s['id'] for s in _walk(plan['sections'])]}\n\n"
    user += format_upstream({note["node_id"]: note["text"] for note in notes})
    raw = llm_chat(system, user, json_mode=True)
    parsed = parse_json_lenient(raw or "")
    if not isinstance(parsed, dict):
        return _scrub(plan, goal)
    title = parsed.get("title")
    if isinstance(title, str) and title.strip() and title.strip() != goal.strip():
        plan["title"] = title.strip()[:48]
    labels = parsed.get("references")
    if isinstance(labels, list):
        plan["references"] = [str(item).strip()[:120] for item in labels if str(item).strip()][:8]
    by_id = {section["id"]: section for section in _walk(plan["sections"])}
    for section in parsed.get("sections") or []:
        if not isinstance(section, dict):
            continue
        target = by_id.get(str(section.get("id") or ""))
        paragraphs = section.get("paragraphs")
        if target is None or not isinstance(paragraphs, list):
            continue
        clean = [str(p).strip()[:4000] for p in paragraphs if str(p).strip()]
        if clean:
            target["paragraphs"] = clean[:8]
        charts = section.get("charts")
        if isinstance(charts, list):
            target["charts"] = [_clean_chart(item) for item in charts]
            target["charts"] = [item for item in target["charts"] if item]
    return _scrub(plan, goal)


def _scrub(plan: dict[str, Any], goal: str) -> dict[str, Any]:
    """Drop paragraphs that just echo the user instruction or the section title."""
    goal_key = re.sub(r"\s+", "", goal or "")
    for section in _walk(plan["sections"]):
        title_key = re.sub(r"\s+", "", section.get("title") or "")
        kept = []
        fallback = [str(item) for item in section.pop("_fallback", []) if str(item).strip()]
        for paragraph in section.get("paragraphs") or []:
            key = re.sub(r"\s+", "", paragraph)
            if not key or key == title_key:
                continue
            if goal_key and (key == goal_key or goal_key in key and len(key) < len(goal_key) + 8):
                continue
            kept.append(paragraph)
        section["paragraphs"] = kept or fallback
    if re.sub(r"\s+", "", plan.get("title") or "") == goal_key:
        plan["title"] = _headline(goal)
    return plan


def _clean_chart(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    labels = item.get("labels")
    values = item.get("values")
    if not isinstance(labels, list) or not isinstance(values, list) or not values:
        return None
    clean_labels: list[str] = []
    clean_values: list[float] = []
    for label, value in zip(labels, values):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        clean_labels.append(str(label)[:40])
        clean_values.append(float(value))
    if not clean_values:
        return None
    chart_id = re.sub(r"[^a-z0-9_-]", "", str(item.get("id") or "chart").lower()) or "chart"
    return {"id": chart_id[:40], "labels": clean_labels, "values": clean_values}


def _citations(notes: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    refs: list[dict[str, str]] = []
    for note in notes:
        for url in extract_urls(note["text"]):
            url = url.rstrip(".,;，。；")
            if url in seen:
                continue
            seen.add(url)
            host = re.sub(r"^https?://", "", url).split("/")[0] or note["node_id"]
            refs.append({"index": str(len(refs) + 1), "url": url, "source": host})
    return refs


def _charts(plan: dict[str, Any], notes: list[dict[str, str]]) -> dict[str, str]:
    series: dict[str, list[tuple[str, float]]] = {}
    blob = "\n".join(note["text"] for note in notes)
    for match in _METRIC.finditer(blob):
        name = match.group("name").lower()
        label = (match.group("label") or name).strip("-_ ") or name
        series.setdefault(name, []).append((label, float(match.group("value"))))
    for section in _walk(plan["sections"]):
        for chart in section.get("charts") or []:
            chart_id = chart["id"]
            pairs = list(zip(chart["labels"], chart["values"]))
            if pairs:
                series[chart_id] = [(str(a), float(b)) for a, b in pairs]
    files: dict[str, str] = {}
    if plan.get("experimental"):
        for name in ("psnr", "ssim", "lpips"):
            files[name] = _bar_svg(name.upper(), series.get(name) or [])
        files["compare"] = _bar_svg("对比", _flatten(series))
    elif series:
        for name, pairs in series.items():
            files[name] = _bar_svg(name, pairs)
    return files


def _flatten(series: dict[str, list[tuple[str, float]]]) -> list[tuple[str, float]]:
    rows: list[tuple[str, float]] = []
    for name, pairs in series.items():
        for label, value in pairs:
            rows.append((f"{name}:{label}", value))
    return rows[:12]


def _bar_svg(title: str, pairs: list[tuple[str, float]]) -> str:
    title_e = html.escape(title)
    if not pairs:
        return (
            "<svg xmlns='http://www.w3.org/2000/svg' width='640' height='160'>"
            f"<text x='24' y='40' font-size='16'>{title_e}</text>"
            "<text x='24' y='80' font-size='14' fill='#666'>上游结果中没有可绘制的数值。</text>"
            "</svg>"
        )
    width, height = 640, 40 + 36 * len(pairs)
    max_value = max(abs(value) for _, value in pairs) or 1.0
    rows = [
        "<svg xmlns='http://www.w3.org/2000/svg' "
        f"width='{width}' height='{height}' role='img'>",
        f"<title>{title_e}</title>",
        f"<text x='16' y='24' font-size='16'>{title_e}</text>",
    ]
    for index, (label, value) in enumerate(pairs[:12]):
        y = 40 + index * 36
        bar = int(abs(value) / max_value * 360)
        rows.append(
            f"<text x='16' y='{y + 16}' font-size='12'>{html.escape(label)}</text>"
            f"<rect x='160' y='{y}' width='{bar}' height='20' fill='#1f6feb'/>"
            f"<text x='{168 + bar}' y='{y + 15}' font-size='12'>{html.escape(str(value))}</text>"
        )
    rows.append("</svg>")
    return "".join(rows)


def _outline_svg(plan: dict[str, Any]) -> str:
    sections = list(_walk(plan["sections"]))
    height = 48 + 28 * len(sections)
    rows = [
        "<svg xmlns='http://www.w3.org/2000/svg' width='640' "
        f"height='{height}' role='img'>",
        f"<title>{html.escape(plan['title'])}</title>",
        "<text x='16' y='28' font-size='16'>Report Plan</text>",
    ]
    for index, section in enumerate(sections):
        y = 56 + index * 28
        label = f"{section['number']} {section['title']}"
        rows.append(f"<text x='24' y='{y}' font-size='14'>{html.escape(label)}</text>")
    rows.append("</svg>")
    return "".join(rows)


def _render_html(
    plan: dict[str, Any],
    citations: list[dict[str, str]],
    charts: dict[str, str],
    diagram: str,
) -> tuple[str, str]:
    del diagram
    summary = next((s for s in plan["sections"] if s["id"] == "summary"), None)
    dek = ""
    if summary and summary.get("paragraphs"):
        dek = summary["paragraphs"][0]
        if len(dek) > 90:
            dek = dek[:90].rstrip("，,。 ") + "…"
    toc = "".join(
        f"<a href='#{html.escape(section['id'])}'>"
        f"<span>{html.escape(section['number'])}</span>{html.escape(section['title'])}</a>"
        for section in plan["sections"]
        if section["id"] != "summary"
    )
    body = "".join(_section_html(section, charts, citations) for section in plan["sections"])
    doc = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{html.escape(plan["title"])}</title>
<style>{_CSS}</style>
</head>
<body>
<article class="sheet">
<header class="cover">
<p class="kicker">AOP Report</p>
<h1>{html.escape(plan["title"])}</h1>
{f"<p class='dek'>{html.escape(dek)}</p>" if dek else ""}
</header>
<nav class="toc">{toc}</nav>
{body}
</article>
</body>
</html>"""
    return sanitize_markup(doc), _CSS


def _section_html(
    section: dict[str, Any],
    charts: dict[str, str],
    citations: list[dict[str, str]],
) -> str:
    number = html.escape(section["number"])
    title = html.escape(section["title"])
    paragraphs = section.get("paragraphs") or []
    if section["id"] == "summary" and paragraphs:
        body = f"<p class='lead'>{html.escape(paragraphs[0])}</p>" + "".join(
            f"<p>{html.escape(p)}</p>" for p in paragraphs[1:]
        )
    else:
        body = "".join(f"<p>{html.escape(p)}</p>" for p in paragraphs)
    figure = ""
    chart_ids: list[str] = []
    if section.get("chart"):
        chart_ids.append(section["chart"])
    chart_ids.extend(chart["id"] for chart in section.get("charts") or [])
    seen: set[str] = set()
    for chart_id in chart_ids:
        if chart_id in seen or chart_id not in charts or "<rect " not in charts[chart_id]:
            continue
        seen.add(chart_id)
        figure += (
            f"<figure><img src='assets/charts/{html.escape(chart_id)}.svg' "
            f"alt='{html.escape(chart_id)}'/><figcaption>{html.escape(chart_id)}</figcaption></figure>"
        )
    extra = ""
    if section["id"] == "references":
        if citations:
            items = []
            for item in citations:
                label = item.get("source") or item.get("url") or ""
                url = item.get("url") or ""
                if url:
                    items.append(
                        f"<li><a href='{html.escape(url, quote=True)}'>{html.escape(url)}</a>"
                        f"<span>{html.escape(item.get('source') or '')}</span></li>"
                    )
                elif label:
                    items.append(f"<li><span>{html.escape(label)}</span></li>")
            extra = f"<ol class='refs'>{''.join(items)}</ol>"
        elif not paragraphs:
            extra = "<p class='muted'>上游结果没有给出可核对的出处。</p>"
    children = "".join(
        _section_html(child, charts, citations) for child in section.get("children") or []
    )
    return (
        f"<section class='block' id='{html.escape(section['id'])}'>"
        f"<div class='num'>{number}</div>"
        f"<div class='copy'><h2>{title}</h2>{body}{figure}{extra}{children}</div>"
        f"</section>"
    )


def _summary(plan: dict[str, Any], citations: list[dict[str, str]], pdf: dict[str, Any]) -> str:
    lines = [f"# {plan['title']}", "", "Report Plan", ""]
    for section in _walk(plan["sections"]):
        lines.append(f"{section['number']}. {section['title']}")
    lines += ["", f"PDF engine: {pdf.get('engine')}", f"Citations: {len(citations)}", ""]
    lines.append("Artifacts: report.html, report.css, assets/charts/, assets/diagrams/")
    return "\n".join(lines)


def _walk(sections: list[dict[str, Any]]):
    for section in sections:
        yield section
        yield from _walk(section.get("children") or [])


_CSS = """
@page { size: A4; margin: 16mm; }
:root { color-scheme: light; }
body { margin: 0; background: #f4f1ea; color: #1c1915; font-family: "Iowan Old Style", "Palatino Linotype", "Songti SC", "Noto Serif SC", serif; }
.sheet { max-width: 760px; margin: 0 auto; background: #fffdf8; padding: 56px 64px 72px; }
.kicker { margin: 0; letter-spacing: 0.22em; text-transform: uppercase; font-family: "Segoe UI", sans-serif; font-size: 11px; color: #8a8175; }
h1 { margin: 12px 0 0; font-size: 40px; line-height: 1.15; font-weight: 560; letter-spacing: -0.02em; }
.dek { margin: 18px 0 0; max-width: 38em; color: #5c564e; font-size: 18px; line-height: 1.55; }
.toc { display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 28px 0 8px; padding: 14px 0; border-top: 1px solid #e6e0d6; border-bottom: 1px solid #e6e0d6; }
.toc a { color: #3f3a34; text-decoration: none; font-family: "Segoe UI", sans-serif; font-size: 12px; }
.toc span { margin-right: 6px; color: #a89880; }
.block { display: grid; grid-template-columns: 52px 1fr; gap: 8px; padding: 22px 0; border-bottom: 1px solid #efeae2; }
.num { font-family: "Segoe UI", sans-serif; font-size: 12px; letter-spacing: 0.08em; color: #a89880; padding-top: 6px; }
h2 { margin: 0 0 10px; font-size: 22px; font-weight: 560; }
p { margin: 0 0 12px; font-size: 16.5px; line-height: 1.75; }
.lead { font-size: 18px; line-height: 1.7; }
.muted { color: #6f685f; }
figure { margin: 8px 0 16px; }
img { max-width: 100%; height: auto; }
figcaption { font-family: "Segoe UI", sans-serif; font-size: 12px; color: #6f685f; }
ol.refs { margin: 0; padding: 0; list-style: none; }
ol.refs li { padding: 8px 0; border-bottom: 1px solid #f3eee6; font-size: 14px; }
ol.refs a { color: #8a5a2a; }
ol.refs span { display: block; color: #6f685f; }
.block .block { grid-template-columns: 42px 1fr; border: 0; padding: 12px 0 0; }
""".strip()
