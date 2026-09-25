"""Local python-pptx stub deck when DeepPresenter is unavailable."""

from __future__ import annotations

import io
import re
from typing import Any

from pptx import Presentation
from pptx.util import Inches, Pt

_UPSTREAM_RE = re.compile(
    r"Upstream results \(via handoff\):\s*(.+?)(?:\nPlease continue|\Z)",
    flags=re.IGNORECASE | re.DOTALL,
)
_GOAL_RE = re.compile(r"^User goal:\s*(.+)$", re.MULTILINE)
_RESULT_ITEM_RE = re.compile(
    r"^\d+\.\s+(.+?)\n\s+(https?://\S+)\n\s+(.+?)(?=\n\d+\.|\n---|\n###|\Z)",
    flags=re.MULTILINE | re.DOTALL,
)
_HEADING_RE = re.compile(r"^###\s+(\S+)", re.MULTILINE)


def _clean(text: str, limit: int = 120) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= limit:
        return t
    return t[: max(0, limit - 1)].rstrip() + "…"


def _extract_goal(query: str) -> str:
    m = _GOAL_RE.search(query or "")
    if m:
        return m.group(1).strip()
    # First non-empty line as fallback
    for line in (query or "").splitlines():
        line = line.strip()
        if line and not line.lower().startswith(("current node", "working memory")):
            return line[:120]
    return "Untitled deck"


def _extract_research_bullets(query: str, *, limit: int = 8) -> list[str]:
    """Pull concrete findings from composed upstream search text."""
    text = query or ""
    m = _UPSTREAM_RE.search(text)
    block = m.group(1) if m else text
    bullets: list[str] = []
    for title, url, snippet in _RESULT_ITEM_RE.findall(block):
        title_c = _clean(title, 80)
        snip_c = _clean(snippet, 140)
        if title_c:
            bullets.append(f"{title_c} — {snip_c}" if snip_c else title_c)
        if url and len(bullets) < limit:
            # Keep URL as a separate short bullet for citation slides
            pass
        if len(bullets) >= limit:
            break
    if not bullets:
        # Fallback: non-empty lines that look like content
        for line in block.splitlines():
            line = line.strip().lstrip("-•* ").strip()
            if len(line) < 12:
                continue
            if line.lower().startswith(
                ("user goal", "current node", "source:", "handoff:", "search results", "###", "opened ")
            ):
                continue
            bullets.append(_clean(line, 160))
            if len(bullets) >= limit:
                break
    return bullets


def has_usable_research(query: str) -> bool:
    """True when the composed prompt contains concrete upstream findings.

    Requires either numbered search hits or an Upstream handoff block with
    non-portal content — bare goals alone do not count.
    """
    text = query or ""
    items = _RESULT_ITEM_RE.findall(text)
    if items:
        good = 0
        for title, url, snippet in items:
            blob = f"{title} {url} {snippet}".lower()
            if any(
                h in blob
                for h in ("sogou.com", "cn.bing.com", "so.com", "17so.cn", "google.com/")
            ):
                continue
            if len(_clean(title, 80)) >= 4:
                good += 1
        return good >= 1

    m = _UPSTREAM_RE.search(text)
    if not m:
        return False
    block = m.group(1)
    bullets = []
    for line in block.splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if len(line) < 12:
            continue
        if line.lower().startswith(
            ("user goal", "current node", "source:", "handoff:", "search results", "###", "opened ", "status:", "confidence:")
        ):
            continue
        low = line.lower()
        if any(h in low for h in ("sogou.com", "cn.bing.com", "so.com", "17so.cn")):
            continue
        bullets.append(line)
        if len(bullets) >= 2:
            break
    return len(bullets) >= 1


def _topic_from_goal(goal: str) -> str:
    """Prefer product/tech token over full imperative sentence."""
    tokens = re.findall(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9+./_-]{1,})(?![A-Za-z0-9])", goal or "")
    skip = {"ppt", "pptx", "pdf", "http", "https", "www", "url"}
    scored = [t for t in tokens if t.lower() not in skip and len(t) >= 2]
    if scored:
        scored.sort(key=lambda t: (any(c.isdigit() for c in t), len(t)), reverse=True)
        return scored[0]
    cleaned = re.sub(
        r"搜索|检索|相关内容|功能介绍|演示|生成|制作|一份|PPTX?|幻灯片",
        " ",
        goal or "",
        flags=re.I,
    )
    cleaned = re.sub(r"[，,。.\s]+", " ", cleaned).strip()
    return cleaned[:40] or (goal[:40] if goal else "Product")


def _slides_from_query(query: str, *, max_slides: int = 6) -> list[tuple[str, list[str]]]:
    goal = _extract_goal(query)
    topic = _topic_from_goal(goal)
    findings = _extract_research_bullets(query, limit=8)

    if findings:
        agenda = ["产品背景", "核心功能", "关键发现", "下一步"]
        background = findings[:3] or [f"围绕 {topic} 的公开资料整理"]
        key_points = findings[3:6] or findings[:3]
        sources = findings[-2:] if len(findings) >= 2 else findings
        outline: list[tuple[str, list[str]]] = [
            (
                f"{topic} 功能介绍",
                [
                    f"主题：{topic}",
                    _clean(goal, 100),
                    "基于上游检索结果自动整理（stub 后端）",
                ],
            ),
            ("目录", agenda),
            ("背景与定位", background),
            ("核心功能 / 要点", key_points),
            ("资料与来源摘要", sources or ["详见上游 search 产物"]),
            (
                "总结",
                [
                    f"{topic} 功能介绍（stub 生成）",
                    "启用 DeepPresenter 可获得更高质量版式",
                    "PPT_MODE=deeppresenter",
                ],
            ),
        ]
    else:
        outline = [
            (
                f"{topic} 功能介绍",
                [
                    _clean(goal, 120),
                    "上游检索无可用要点，本页为占位大纲",
                    "请检查 search 节点结果后重试",
                ],
            ),
            ("目录", ["背景", "功能要点", "下一步"]),
            ("背景", [f"待补充：{topic} 的产品背景"]),
            ("功能要点", ["待补充：核心能力", "待补充：差异化卖点", "待补充：适用场景"]),
            ("建议", ["先修好检索相关性", "再生成正式演示稿"]),
            ("总结", ["Stub 大纲占位", "有检索结果后会自动填入要点"]),
        ]
    return outline[: max(1, max_slides)]


def build_stub_pptx(query: str, *, max_slides: int = 6) -> tuple[bytes, dict[str, Any]]:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    slides = _slides_from_query(query, max_slides=max_slides)

    for i, (heading, bullets) in enumerate(slides):
        slide = prs.slides.add_slide(blank)
        title_box = slide.shapes.add_textbox(Inches(0.6), Inches(0.4), Inches(12), Inches(1))
        tf = title_box.text_frame
        p = tf.paragraphs[0]
        p.text = heading
        p.font.size = Pt(32 if i == 0 else 28)
        p.font.bold = True

        body = slide.shapes.add_textbox(Inches(0.8), Inches(1.6), Inches(11.5), Inches(5))
        btf = body.text_frame
        btf.clear()
        for j, line in enumerate(bullets):
            para = btf.paragraphs[0] if j == 0 else btf.add_paragraph()
            para.text = line
            para.font.size = Pt(18)
            para.level = 0

    buf = io.BytesIO()
    prs.save(buf)
    raw = buf.getvalue()
    meta = {
        "source": "stub",
        "slide_count": len(slides),
        "format": "pptx",
        "note": "Stub python-pptx deck built from upstream research. Set PPT_MODE=deeppresenter when aop-deeppresenter is running.",
        "topic": _topic_from_goal(_extract_goal(query)),
    }
    return raw, meta
