"""Enhanced context parsing with unified LLM Provider (Phase 37.2)."""

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
                timeout=60.0,
                max_retries=3,
                temperature=0.2,
            )
            get_llm_provider._instance = OpenAIProvider(config)
            print(f"[Analysis Agent] LLM provider initialized: {config.model}")
        except Exception as e:
            print(f"[Analysis Agent] Failed to initialize LLM provider: {e}")
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
            print(f"[Analysis Agent] Unexpected finish reason: {response.finish_reason}")
            return None
            
    except LLMError as e:
        print(f"[Analysis Agent] LLM error: {e.to_dict()}")
        return None
    except Exception as e:
        print(f"[Analysis Agent] Unexpected error: {e}")
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


def llm_analysis_with_metadata(goal: str, upstream: dict[str, Any]) -> dict[str, Any] | None:
    """Enhanced LLM analysis with execution metadata."""
    provider = get_llm_provider()
    if not provider:
        return None
    
    system = (
        "You are a business analyst for a multi-agent AI orchestration platform. "
        "Analyze the provided research context (web search results and knowledge-base "
        "retrieval) and produce concise, specific, evidence-grounded insights. "
        "Respond in the same language as the goal. Return ONLY a JSON object with keys "
        '"summary" (string) and "insights" (array of {"theme", "detail"} objects).'
    )
    user = f"Goal: {goal}"
    if upstream:
        user += f"\n\nUpstream results:\n{format_upstream(upstream)}"

    try:
        request = provider.create_request(
            messages=[
                provider.create_system_message(system),
                provider.create_user_message(user),
            ],
            response_format={"type": "json_object"},
        )
        
        response = provider.chat_completion(request)
        
        if response.finish_reason != "stop":
            print(f"[Analysis Agent] Unexpected finish reason: {response.finish_reason}")
            return None
        
        data = parse_json_lenient(response.content)
        if not isinstance(data, dict):
            print(f"[Analysis Agent] Failed to parse JSON response")
            return None
        
        summary = str(data.get("summary") or "").strip()
        insights = data.get("insights")
        if not summary or not isinstance(insights, list) or not insights:
            print(f"[Analysis Agent] Invalid response structure")
            return None
        
        # Return with metadata
        return {
            "summary": summary,
            "insights": insights,
            "metadata": {
                "model": response.model,
                "tokens_used": response.usage.get("total_tokens", 0),
                "latency_ms": response.latency_ms,
                "provider": response.provider,
            }
        }
        
    except LLMError as e:
        print(f"[Analysis Agent] LLM error: {e.to_dict()}")
        return None
    except Exception as e:
        print(f"[Analysis Agent] Unexpected error: {e}")
        return None
