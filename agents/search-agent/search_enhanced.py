"""Enhanced Search Agent with real LLM integration (Phase 37.2)."""

from __future__ import annotations

import os
import asyncio
from typing import Any
from urllib.parse import quote_plus
import functools

import httpx

from llm_provider import (
    OpenAIProvider,
    LLMProviderConfig,
    ProviderType,
    LLMError,
    LLMErrorType,
)
from agent_runtime import (
    AgentRuntime,
    Tool,
    ToolResult,
    ToolLoopConfig,
)
from agent_runtime.tool_loop import ToolCallingLoop

USER_AGENT = "AOP-SearchAgent/0.3 (+https://github.com/aop)"


def run_async(coro):
    """Helper to run async coroutine, compatible with both sync and async contexts."""
    try:
        loop = asyncio.get_running_loop()
        # If there's a running loop, create a task
        future = asyncio.ensure_future(coro)
        # Return a callback that can be awaited
        return future
    except RuntimeError:
        # No running loop, use asyncio.run
        return asyncio.run(coro)


class SearchAgentRuntime(AgentRuntime):
    """Search Agent with LLM-powered query understanding and result synthesis."""
    
    def __init__(self):
        config = ToolLoopConfig(
            max_iterations=3,
            continue_on_tool_error=True,
        )
        super().__init__()
        self._loop_config = config
        self._llm_provider = None
        self._search_backends = []
        self._initialize_llm()
        self._setup_search_tools()
    
    def _initialize_llm(self) -> None:
        """Initialize LLM provider if API key is available."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("[Search Agent] No OPENAI_API_KEY found, operating in direct search mode")
            return
        
        try:
            config = LLMProviderConfig(
                provider_type=ProviderType.OPENAI,
                api_key=api_key,
                base_url=os.getenv("OPENAI_BASE_URL"),
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                timeout=30.0,
                max_retries=2,
            )
            self._llm_provider = OpenAIProvider(config)
            print(f"[Search Agent] LLM provider initialized: {config.model}")
        except Exception as e:
            print(f"[Search Agent] Failed to initialize LLM provider: {e}")
            self._llm_provider = None
    
    def _setup_search_tools(self) -> None:
        """Register search tools for LLM to use."""
        
        def duckduckgo_search_handler(params):
            """DuckDuckGo Instant Answer API search."""
            query = params.get("query", "")
            limit = params.get("limit", 5)
            # Use sync version to avoid asyncio conflicts
            return self._duckduckgo_instant_sync(query, limit=limit)
        
        def wikipedia_search_handler(params):
            """Wikipedia OpenSearch API."""
            query = params.get("query", "")
            limit = params.get("limit", 5)
            lang = params.get("lang", "en")
            return self._wikipedia_opensearch_sync(query, limit=limit, lang=lang)
        
        def web_search_handler(params):
            """Comprehensive web search with multiple backends."""
            query = params.get("query", "")
            limit = params.get("limit", 5)
            return self._comprehensive_search_sync(query, limit=limit)
        
        # Register tools
        ddg_tool = Tool(
            name="duckduckgo_search",
            description="Search using DuckDuckGo Instant Answer API for quick results",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Number of results (default: 5)"},
                },
                "required": ["query"],
            },
            handler=duckduckgo_search_handler,
        )
        
        wiki_tool = Tool(
            name="wikipedia_search",
            description="Search Wikipedia for encyclopedic information",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Number of results (default: 5)"},
                    "lang": {"type": "string", "description": "Language code (default: en)"},
                },
                "required": ["query"],
            },
            handler=wikipedia_search_handler,
        )
        
        web_tool = Tool(
            name="web_search",
            description="Comprehensive web search using multiple backends",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Number of results (default: 5)"},
                },
                "required": ["query"],
            },
            handler=web_search_handler,
        )
        
        self.register_tool(ddg_tool)
        self.register_tool(wiki_tool)
        self.register_tool(web_tool)
    
    async def _duckduckgo_instant(self, query: str, *, limit: int = 5) -> ToolResult:
        """DuckDuckGo Instant Answer JSON API."""
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(
                    "https://api.duckduckgo.com/",
                    params={
                        "q": query,
                        "format": "json",
                        "no_html": "1",
                        "skip_disambig": "1",
                    },
                    headers={"User-Agent": USER_AGENT},
                )
                if resp.status_code != 200:
                    return ToolResult(
                        success=False,
                        content="",
                        error=f"DuckDuckGo API returned status {resp.status_code}",
                    )
                data = resp.json()
        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"DuckDuckGo search failed: {str(e)}",
            )
        
        results = []
        abstract = (data.get("AbstractText") or "").strip()
        abstract_url = (data.get("AbstractURL") or "").strip()
        heading = (data.get("Heading") or query).strip()
        
        if abstract and abstract_url:
            results.append({"title": heading, "url": abstract_url, "snippet": abstract[:400]})
        
        for topic in data.get("RelatedTopics") or []:
            if len(results) >= limit:
                break
            if isinstance(topic, dict) and "Topics" in topic:
                for sub in topic.get("Topics") or []:
                    if len(results) >= limit:
                        break
                    text = (sub.get("Text") or "").strip()
                    url = (sub.get("FirstURL") or "").strip()
                    if text and url:
                        results.append({
                            "title": text.split(" - ")[0][:120],
                            "url": url,
                            "snippet": text[:400]
                        })
            elif isinstance(topic, dict):
                text = (topic.get("Text") or "").strip()
                url = (topic.get("FirstURL") or "").strip()
                if text and url:
                    results.append({
                        "title": text.split(" - ")[0][:120],
                        "url": url,
                        "snippet": text[:400]
                    })
        
        if not results:
            return ToolResult(
                success=False,
                content="",
                error="No results found from DuckDuckGo",
            )
        
        return ToolResult(
            success=True,
            content=f"Found {len(results)} results from DuckDuckGo",
            data={"results": results, "source": "duckduckgo-instant"},
        )
    
    def _duckduckgo_instant_sync(self, query: str, *, limit: int = 5) -> ToolResult:
        """Sync DuckDuckGo search using httpx sync client."""
        try:
            resp = httpx.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=8.0,
            )
            if resp.status_code != 200:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"DuckDuckGo API returned status {resp.status_code}",
                )
            data = resp.json()
        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"DuckDuckGo search failed: {str(e)}",
            )
        
        results = []
        abstract = (data.get("AbstractText") or "").strip()
        abstract_url = (data.get("AbstractURL") or "").strip()
        heading = (data.get("Heading") or query).strip()
        
        if abstract and abstract_url:
            results.append({"title": heading, "url": abstract_url, "snippet": abstract[:400]})
        
        for topic in data.get("RelatedTopics") or []:
            if len(results) >= limit:
                break
            if isinstance(topic, dict) and "Topics" in topic:
                for sub in topic.get("Topics") or []:
                    if len(results) >= limit:
                        break
                    text = (sub.get("Text") or "").strip()
                    url = (sub.get("FirstURL") or "").strip()
                    if text and url:
                        results.append({
                            "title": text.split(" - ")[0][:120],
                            "url": url,
                            "snippet": text[:400]
                        })
            elif isinstance(topic, dict):
                text = (topic.get("Text") or "").strip()
                url = (topic.get("FirstURL") or "").strip()
                if text and url:
                    results.append({
                        "title": text.split(" - ")[0][:120],
                        "url": url,
                        "snippet": text[:400]
                    })
        
        if not results:
            return ToolResult(
                success=False,
                content="",
                error="No results found from DuckDuckGo",
            )
        
        return ToolResult(
            success=True,
            content=f"Found {len(results)} results from DuckDuckGo",
            data={"results": results, "source": "duckduckgo-instant"},
        )
    
    def _wikipedia_opensearch_sync(self, query: str, *, limit: int = 5, lang: str = "en") -> ToolResult:
        """Sync Wikipedia search using httpx sync client."""
        lang = (os.getenv("SEARCH_WIKI_LANG") or lang).strip() or "en"
        try:
            resp = httpx.get(
                f"https://{lang}.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": query,
                    "limit": str(limit),
                    "namespace": "0",
                    "format": "json",
                },
                headers={"User-Agent": USER_AGENT},
                timeout=8.0,
            )
            if resp.status_code != 200:
                return ToolResult(
                    success=False,
                    content="",
                    error=f"Wikipedia API returned status {resp.status_code}",
                )
            data = resp.json()
        except Exception as e:
            return ToolResult(
                success=False,
                content="",
                error=f"Wikipedia search failed: {str(e)}",
            )
        
        if not isinstance(data, list) or len(data) < 4:
            return ToolResult(
                success=False,
                content="",
                error="Invalid Wikipedia API response",
            )
        
        titles, descs, urls = data[1], data[2], data[3]
        results = []
        for i, title in enumerate(titles):
            results.append({
                "title": title,
                "url": urls[i] if i < len(urls) else "",
                "snippet": descs[i] if i < len(descs) else "",
            })
        
        return ToolResult(
            success=True,
            content=f"Found {len(results)} results from Wikipedia",
            data={"results": results, "source": "wikipedia"},
        )
    
    def _comprehensive_search_sync(self, query: str, *, limit: int = 5) -> ToolResult:
        """Sync comprehensive search using multiple backends."""
        backends = [
            ("DuckDuckGo Instant", self._duckduckgo_instant_sync),
            ("Wikipedia", self._wikipedia_opensearch_sync),
        ]
        
        for name, fn in backends:
            try:
                result = fn(query, limit=limit)
                if result.success:
                    result.data["source"] = name
                    return result
            except Exception as e:
                print(f"[Search Agent] {name} failed: {e}")
                continue
        
        return ToolResult(
            success=False,
            content="",
            error="All search backends failed - no mock fallback available",
        )
    
    def get_llm_provider(self):
        """Get the LLM provider for this agent."""
        return self._llm_provider
    
    def execute_search(self, query: str, use_llm: bool = True) -> dict[str, Any]:
        """Execute search with optional LLM enhancement."""
        
        # Direct search mode (no LLM)
        if not use_llm or not self._llm_provider:
            print(f"[Search Agent] Direct search mode for: {query}")
            result = self._comprehensive_search_sync(query, limit=5)
            
            if not result.success:
                return {
                    "query": query,
                    "source": "error",
                    "results": [],
                    "error": result.error,
                    "summary": f"Search failed: {result.error}",
                }
            
            # Format results
            results = result.data.get("results", [])
            summary_lines = [f"Search results for: {query}", f"Source: {result.data.get('source', 'unknown')}", ""]
            for i, item in enumerate(results, 1):
                summary_lines.append(f"{i}. {item['title']}")
                summary_lines.append(f"   {item['url']}")
                if item.get("snippet"):
                    summary_lines.append(f"   {item['snippet']}")
                summary_lines.append("")
            
            return {
                "query": query,
                "source": result.data.get("source", "direct"),
                "results": results,
                "summary": "\n".join(summary_lines).strip(),
                "mode": "direct",
            }
        
        # LLM-enhanced search mode
        print(f"[Search Agent] LLM-enhanced search for: {query}")
        
        system_prompt = """You are a search assistant. When the user asks for information, use the available search tools to find relevant results. 
Synthesize the search results into a clear, concise summary. Always cite your sources with URLs."""
        
        loop = ToolCallingLoop(self._llm_provider, self, self._loop_config)
        
        try:
            execution_result = loop.execute(
                system_prompt=system_prompt,
                user_prompt=query,
                tools=self.tool_registry.to_openai_format(),
                tool_choice="auto",
            )
            
            if execution_result.success:
                return {
                    "query": query,
                    "source": "llm-enhanced",
                    "results": [],  # LLM synthesis doesn't return raw results
                    "summary": execution_result.content,
                    "mode": "llm-enhanced",
                    "metadata": execution_result.metadata.to_dict(),
                }
            else:
                # Fallback to direct search on LLM failure
                print(f"[Search Agent] LLM search failed, falling back to direct: {execution_result.metadata.error}")
                return self.execute_search(query, use_llm=False)
                
        except LLMError as e:
            print(f"[Search Agent] LLM error: {e}, falling back to direct search")
            return self.execute_search(query, use_llm=False)
        except Exception as e:
            print(f"[Search Agent] Unexpected error: {e}, falling back to direct search")
            return self.execute_search(query, use_llm=False)


# Global instance for backward compatibility
_search_runtime = None

def get_search_runtime():
    """Get or create the search runtime instance."""
    global _search_runtime
    if _search_runtime is None:
        _search_runtime = SearchAgentRuntime()
    return _search_runtime


async def run_search(query: str) -> dict[str, Any]:
    """Enhanced search function with LLM integration (Phase 37.2)."""
    runtime = get_search_runtime()
    
    # Determine if we should use LLM based on environment
    use_llm = os.getenv("SEARCH_USE_LLM", "auto").lower() == "true"
    
    # For now, default to direct search to maintain compatibility
    # Set SEARCH_USE_LLM=true to enable LLM enhancement
    if use_llm and runtime._llm_provider:
        return runtime.execute_search(query, use_llm=True)
    else:
        return runtime.execute_search(query, use_llm=False)


def run_search_sync(query: str) -> dict[str, Any]:
    """Sync wrapper for run_search to avoid asyncio conflicts."""
    try:
        loop = asyncio.get_running_loop()
        # If in async context, run direct search
        runtime = get_search_runtime()
        return runtime.execute_search(query, use_llm=False)
    except RuntimeError:
        # No running loop, use async version
        return asyncio.run(run_search(query))
