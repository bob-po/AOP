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

from search import mock_results, _parse_bing

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
                timeout=180.0,
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
    
    def _bing_raw(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Raw Bing results (reachable from China), or [] on failure."""
        endpoint = (
            os.getenv("SEARCH_BING_ENDPOINT", "https://cn.bing.com/search").strip()
            or "https://cn.bing.com/search"
        )
        try:
            resp = httpx.get(
                endpoint,
                params={"q": query, "count": str(max(1, min(limit, 30)))},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
                timeout=10.0,
            )
            if resp.status_code != 200:
                return []
            return _parse_bing(resp.text, limit=limit)
        except Exception as e:  # noqa: BLE001
            print(f"[Search Agent] Bing search failed: {e}")
            return []

    def _comprehensive_search_sync(self, query: str, *, limit: int = 5) -> ToolResult:
        """Sync comprehensive search using multiple backends, with mock fallback."""
        # Bing first: the only live backend reachable from this network.
        bing = self._bing_raw(query, limit=limit)
        if bing:
            return ToolResult(
                success=True,
                content=f"Found {len(bing)} results from Bing",
                data={"results": bing, "source": "bing"},
            )

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

        # Graceful offline fallback: mirror search.py's mock results so the
        # search node still completes when live backends are unreachable.
        results = mock_results(query)
        return ToolResult(
            success=True,
            content=f"Found {len(results)} mock results (live backends unreachable)",
            data={"results": results, "source": "mock-fallback"},
        )
    
    def get_llm_provider(self):
        """Get the LLM provider for this agent."""
        return self._llm_provider
    
    def _llm_knowledge_search(self, query: str) -> dict[str, Any]:
        """Direct LLM research synthesis (no tools) for offline/blocked networks."""
        system_prompt = (
            "You are a research assistant. Provide a concise but substantive "
            "research overview of the topic the user asks about, using your own "
            "knowledge. Cover what it is, key capabilities, positioning, notable "
            "context, and any relevant caveats. Answer in the same language as "
            "the user's query. Do not claim to have performed a live web search."
        )
        try:
            request = self._llm_provider.create_request(
                messages=[
                    self._llm_provider.create_system_message(system_prompt),
                    self._llm_provider.create_user_message(query),
                ],
            )
            response = self._llm_provider.chat_completion(request)
            content = (response.content or "").strip()
        except Exception as e:  # noqa: BLE001
            print(f"[Search Agent] LLM knowledge search failed: {e}")
            return self.execute_search(query, use_llm=False)

        if not content:
            print("[Search Agent] LLM returned empty content, falling back to direct search")
            return self.execute_search(query, use_llm=False)

        summary_lines = [
            f"Search results for: {query}",
            "Source: llm-knowledge",
            "",
            content,
        ]
        return {
            "query": query,
            "source": "llm-knowledge",
            "results": [{"title": query, "url": "", "snippet": content[:400]}],
            "summary": "\n".join(summary_lines).strip(),
            "mode": "llm-knowledge",
        }

    def _refine_query(self, goal: str) -> str | None:
        """LLM: rewrite a natural-language goal into a concise web-search query."""
        if not self._llm_provider:
            return None
        system = (
            "You are a search-query rewriter. Given a natural-language research request, "
            "output ONLY a concise, keyword-based web search query (2-8 words) in the "
            "original language. Strip instruction words like 'help me', 'research', "
            "'generate a report/image'. No punctuation, no quotes."
        )
        try:
            request = self._llm_provider.create_request(
                messages=[
                    self._llm_provider.create_system_message(system),
                    self._llm_provider.create_user_message(goal),
                ],
            )
            response = self._llm_provider.chat_completion(request)
            q = (response.content or "").strip().strip('"\'')
            q = q.splitlines()[0].strip() if q else ""
            return q or None
        except Exception as e:  # noqa: BLE001
            print(f"[Search Agent] Query refinement failed: {e}")
            return None

    def _llm_synthesize(self, query: str, results: list[dict[str, Any]], source: str) -> dict[str, Any]:
        """Synthesize a research overview grounded ONLY in the provided live results."""
        system = (
            "You are a research assistant. The user asked a research question and you "
            "were given live web search results. Synthesize a concise, accurate research "
            "overview grounded ONLY in the provided results, citing them by number [1], "
            "[2], etc. Answer in the same language as the query."
        )
        context = "\n\n".join(
            f"[{i}] {r['title']}\n{r['url']}\n{r['snippet']}"
            for i, r in enumerate(results, 1)
        )
        content = ""
        try:
            request = self._llm_provider.create_request(
                messages=[
                    self._llm_provider.create_system_message(system),
                    self._llm_provider.create_user_message(f"Query: {query}\n\nWeb results:\n{context}"),
                ],
            )
            response = self._llm_provider.chat_completion(request)
            content = (response.content or "").strip()
        except Exception as e:  # noqa: BLE001
            print(f"[Search Agent] LLM synthesis failed: {e}")

        summary_lines = [f"Search results for: {query}", f"Source: {source} (real-time web)", ""]
        if content:
            summary_lines.append(content)
        else:
            for i, item in enumerate(results, 1):
                summary_lines.append(f"{i}. {item['title']}")
                summary_lines.append(f"   {item['url']}")
                if item.get("snippet"):
                    summary_lines.append(f"   {item['snippet']}")
                summary_lines.append("")

        return {
            "query": query,
            "source": source,
            "results": results,
            "summary": "\n".join(summary_lines).strip(),
            "mode": "llm-synthesis",
        }

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
        
        # LLM-enhanced search mode: rewrite the goal into a clean search query,
        # fetch real-time web results (Bing), then synthesize an overview grounded
        # in those results. Fall back to the model's own knowledge only when no
        # live backend is reachable.
        print(f"[Search Agent] LLM-enhanced search for: {query}")
        refined = self._refine_query(query) or query
        if refined != query:
            print(f"[Search Agent] Refined query: {refined}")
        bing = self._bing_raw(refined, limit=5)
        if bing:
            return self._llm_synthesize(query, bing, source="bing")
        return self._llm_knowledge_search(query)


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
        runtime = get_search_runtime()
        use_llm = (
            os.getenv("SEARCH_USE_LLM", "auto").lower() == "true"
            and runtime._llm_provider is not None
        )
        return runtime.execute_search(query, use_llm=use_llm)
    except RuntimeError:
        # No running loop, use async version
        return asyncio.run(run_search(query))
