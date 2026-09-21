"""Enhanced context parsing with unified LLM Provider for Report Agent (Phase 37.2)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from llm_provider import (
    OpenAIProvider,
    LLMProviderConfig,
    ProviderType,
    LLMError,
    LLMErrorType,
)


def parse_composed_query(text: str) -> dict[str, Any]:
    """Return ``{"goal": str, "upstream": {node_id: section_text}}``.

    Handles both the executor-composed prompt and a bare single-node goal.
    """
    text = text or ""
    goal = ""
    m = re.search(r"^User goal:\s*(.+)$", text, re.MULTILINE)
    if m:
        goal = m.group(1).strip()
    if not goal:
        goal = text.strip()

    upstream: dict[str, str] = {}
    header_re = re.compile(r"^###\s+([^\s()]+)\s*\(([^)]*)\)\s*$", re.MULTILINE)
    matches = list(header_re.finditer(text))
    for i, match in enumerate(matches):
        node_id = match.group(1)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end]
        body = re.sub(
            r"^Please continue based on the upstream results\..*$",
            "",
            body,
            flags=re.MULTILINE,
        )
        upstream[node_id] = body.strip()
    return {"goal": goal, "upstream": upstream}


def llm_available() -> bool:
    """Check if LLM provider is available."""
    return bool(os.getenv("OPENAI_API_KEY"))


def get_llm_provider():
    """Get or create the LLM provider instance."""
    if not hasattr(get_llm_provider, "_instance"):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        
        try:
            config = LLMProviderConfig(
                provider_type=ProviderType.OPENAI,
                api_key=api_key,
                base_url=os.getenv("OPENAI_BASE_URL"),
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                timeout=180.0,
                max_retries=3,
                temperature=0.3,  # Slightly higher temperature for more creative reports
            )
            get_llm_provider._instance = OpenAIProvider(config)
            print(f"[Report Agent] LLM provider initialized: {config.model}")
        except Exception as e:
            print(f"[Report Agent] Failed to initialize LLM provider: {e}")
            get_llm_provider._instance = None
    
    return get_llm_provider._instance


def llm_chat(system: str, user: str, *, json_mode: bool = False) -> str | None:
    """OpenAI-compatible chat completion using unified LLM Provider.
    
    Returns content, or None on failure.
    """
    provider = get_llm_provider()
    if not provider:
        return None
    
    try:
        request = provider.create_request(
            messages=[
                provider.create_system_message(system),
                provider.create_user_message(user),
            ],
            response_format={"type": "json_object"} if json_mode else None,
        )
        
        response = provider.chat_completion(request)
        
        if response.finish_reason == "stop":
            return response.content
        else:
            print(f"[Report Agent] Unexpected finish reason: {response.finish_reason}")
            return None
            
    except LLMError as e:
        print(f"[Report Agent] LLM error: {e.to_dict()}")
        return None
    except Exception as e:
        print(f"[Report Agent] Unexpected error: {e}")
        return None


def parse_json_lenient(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object extraction (tolerates ```json fences)."""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        try:
            return json.loads(fence.group(1))
        except Exception:  # noqa: BLE001
            pass
    obj = re.search(r"\{.*\}", text, re.DOTALL)
    if obj:
        try:
            return json.loads(obj.group(0))
        except Exception:  # noqa: BLE001
            return None
    return None


def extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s)]+", text or "")


def format_upstream(upstream: dict[str, str]) -> str:
    """Render upstream sections for an LLM prompt."""
    blocks = []
    for node_id, body in upstream.items():
        if body:
            blocks.append(f"### {node_id}\n{body}")
    return "\n\n".join(blocks)


def llm_report_with_metadata(goal: str, upstream: dict[str, Any]) -> str | None:
    """Enhanced LLM report generation with execution metadata.
    
    Generates a comprehensive markdown report based on structured upstream data
    instead of simple template concatenation.
    """
    provider = get_llm_provider()
    if not provider:
        return None
    
    # Build structured context from upstream data
    upstream_context = []
    for node_id, content in upstream.items():
        # Try to extract structured data from content
        # This handles both raw text and JSON data from previous agents
        upstream_context.append(f"## {node_id}")
        upstream_context.append(content)
        upstream_context.append("")
    
    system = (
        "You are a professional report writer for a multi-agent AI orchestration platform. "
        "Synthesize the provided research context (web search, knowledge-base retrieval, "
        "business analysis) into a clear, well-structured markdown report with these sections:\n"
        "- Executive Summary\n"
        "- Research Findings\n"
        "- Knowledge Base Insights\n"
        "- Business Analysis\n"
        "- Recommendations\n\n"
        "Ground every claim in the provided upstream content. Use proper markdown formatting. "
        "Respond in the same language as the goal. Output markdown only."
    )
    
    user = f"Goal: {goal}\n\n"
    if upstream_context:
        user += "Upstream Results:\n\n" + "\n".join(upstream_context)
    
    try:
        request = provider.create_request(
            messages=[
                provider.create_system_message(system),
                provider.create_user_message(user),
            ],
        )
        
        response = provider.chat_completion(request)
        
        if response.finish_reason != "stop":
            print(f"[Report Agent] Unexpected finish reason: {response.finish_reason}")
            return None
        
        # Log metadata
        print(f"[Report Agent] Report generated: {response.usage.get('total_tokens', 0)} tokens, {response.latency_ms}ms")
        
        return response.content
        
    except LLMError as e:
        print(f"[Report Agent] LLM error: {e.to_dict()}")
        return None
    except Exception as e:
        print(f"[Report Agent] Unexpected error: {e}")
        return None


def extract_structured_data(upstream: dict[str, str]) -> dict[str, Any]:
    """Extract structured data from upstream results for better report generation."""
    structured_data = {}
    
    for node_id, content in upstream.items():
        # Try to parse JSON data from content
        try:
            # Look for JSON blocks in the content
            json_match = re.search(r'\{[^}]*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                structured_data[node_id] = data
            else:
                # Store as text if no JSON found
                structured_data[node_id] = {"text": content}
        except json.JSONDecodeError:
            # Store as text if JSON parsing fails
            structured_data[node_id] = {"text": content}
    
    return structured_data
