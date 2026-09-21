"""Enhanced RAG Agent with tenant isolation and citation tracing (Phase 37.2)."""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Any, Optional
from datetime import datetime, timezone

from vector_index import TfidfIndex
from llm_provider import (
    OpenAIProvider,
    LLMProviderConfig,
    ProviderType,
    LLMError,
    LLMErrorType,
)


class TenantAwareRAG:
    """RAG with tenant isolation and citation tracing."""
    
    def __init__(self, tenant_id: Optional[str] = None):
        self.tenant_id = tenant_id or os.getenv("DEFAULT_TENANT_ID", "default")
        self._index = None
        self._corpus = None
        self._llm_provider = None
        self._initialize_llm()
    
    def _initialize_llm(self) -> None:
        """Initialize LLM provider for enhanced RAG responses."""
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("[RAG Agent] No OPENAI_API_KEY found, operating in direct RAG mode")
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
            print(f"[RAG Agent] LLM provider initialized: {config.model}")
        except Exception as e:
            print(f"[RAG Agent] Failed to initialize LLM provider: {e}")
            self._llm_provider = None
    
    def load_tenant_corpus(self, corpus_path: Optional[Path] = None) -> list[dict[str, Any]]:
        """Load corpus with tenant isolation."""
        if corpus_path is None:
            corpus_path = Path(__file__).parent / "knowledge" / "corpus.json"
        
        if not corpus_path.exists():
            print(f"[RAG Agent] Corpus file not found: {corpus_path}")
            return []
        
        try:
            data = json.loads(corpus_path.read_text(encoding="utf-8"))
            documents = list(data.get("documents") or [])
            
            # Filter by tenant if documents have tenant_id field
            if self.tenant_id != "default":
                tenant_filtered = [
                    doc for doc in documents 
                    if doc.get("tenant_id") in (self.tenant_id, "shared", None)
                ]
                if len(tenant_filtered) < len(documents):
                    print(f"[RAG Agent] Filtered {len(documents)} -> {len(tenant_filtered)} documents for tenant {self.tenant_id}")
                return tenant_filtered
            
            return documents
        except Exception as e:
            print(f"[RAG Agent] Failed to load corpus: {e}")
            return []
    
    def get_index(self) -> TfidfIndex:
        """Get or create TF-IDF index."""
        if self._index is None:
            self._corpus = self.load_tenant_corpus()
            self._index = TfidfIndex()
            self._index.fit(self._corpus)
            print(f"[RAG Agent] Index built with {len(self._corpus)} documents for tenant {self.tenant_id}")
        return self._index
    
    def search_with_citations(
        self, 
        query: str, 
        top_k: int = 3,
        alpha: float = 0.65
    ) -> dict[str, Any]:
        """Search with enhanced citation tracing."""
        index = self.get_index()
        scored = index.search(query, top_k=top_k, hybrid_alpha=alpha)
        
        citations = []
        for item in scored:
            d = item.doc
            citation = {
                "doc_id": d.get("doc_id"),
                "title": d.get("title"),
                "snippet": (d.get("content") or "")[:280],
                "tags": d.get("tags") or [],
                "score": round(item.score, 4),
                "vector_score": round(item.vector_score, 4),
                "keyword_score": round(item.keyword_score, 4),
                "tenant_id": d.get("tenant_id", "default"),
                "source": d.get("source", "internal"),
            }
            citations.append(citation)
        
        method = "hybrid-tfidf"
        if not citations and self._corpus:
            # Soft fallback for isolation scenarios
            print(f"[RAG Agent] No results for tenant {self.tenant_id}, checking shared documents")
            shared_docs = [d for d in self._corpus if d.get("tenant_id") in ("shared", None)]
            if shared_docs:
                # Temporarily reindex with shared documents
                temp_index = TfidfIndex()
                temp_index.fit(shared_docs)
                scored = temp_index.search(query, top_k=top_k, hybrid_alpha=alpha)
                for item in scored:
                    d = item.doc
                    citations.append({
                        "doc_id": d.get("doc_id"),
                        "title": d.get("title"),
                        "snippet": (d.get("content") or "")[:280],
                        "tags": d.get("tags") or [],
                        "score": round(item.score, 4),
                        "vector_score": round(item.vector_score, 4),
                        "keyword_score": round(item.keyword_score, 4),
                        "tenant_id": d.get("tenant_id", "shared"),
                        "source": d.get("source", "internal"),
                    })
                method = "shared-fallback"
        
        if citations:
            # Build answer with proper citation format
            answer_parts = []
            answer_parts.append(f"Based on the knowledge base (method={method}, tenant={self.tenant_id}) for '{query}':")
            
            for i, citation in enumerate(citations, 1):
                answer_parts.append(f"\n{i}. {citation['title']}")
                answer_parts.append(f"   {citation['snippet']}")
                answer_parts.append(f"   Score: {citation['score']} | Tenant: {citation['tenant_id']}")
                if citation['tags']:
                    answer_parts.append(f"   Tags: {', '.join(citation['tags'])}")
            
            answer = "\n".join(answer_parts)
        else:
            answer = (
                f"No corpus hit for '{query}' in tenant {self.tenant_id}. "
                f"Ensure agents/rag-agent/knowledge/corpus.json contains documents for this tenant."
            )
        
        return {
            "query": query,
            "answer": answer,
            "citations": citations,
            "corpus_size": len(self._corpus),
            "method": method,
            "hybrid_alpha": alpha,
            "tenant_id": self.tenant_id,
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "isolation_mode": "tenant-aware",
            }
        }
    
    def llm_enhanced_answer(
        self, 
        query: str, 
        citations: list[dict[str, Any]],
        context: Optional[str] = None
    ) -> Optional[str]:
        """Generate LLM-enhanced answer with proper citation integration."""
        if not self._llm_provider:
            return None
        
        # Build citation context
        citation_context = []
        for i, citation in enumerate(citations, 1):
            citation_context.append(f"[{i}] {citation['title']}: {citation['snippet'][:200]}")
        
        system_prompt = """You are a knowledge retrieval assistant. Answer the user's question based on the provided citations from the knowledge base. 
Always cite your sources using the citation numbers [1], [2], etc. Be accurate and concise."""
        
        user_prompt = f"Question: {query}\n\n"
        if context:
            user_prompt += f"Additional Context: {context}\n\n"
        user_prompt += f"Citations:\n" + "\n".join(citation_context)
        
        try:
            request = self._llm_provider.create_request(
                messages=[
                    self._llm_provider.create_system_message(system_prompt),
                    self._llm_provider.create_user_message(user_prompt),
                ],
            )
            
            response = self._llm_provider.chat_completion(request)
            
            if response.finish_reason == "stop":
                print(f"[RAG Agent] LLM-enhanced answer: {response.usage.get('total_tokens', 0)} tokens")
                return response.content
            else:
                print(f"[RAG Agent] Unexpected finish reason: {response.finish_reason}")
                return None
                
        except LLMError as e:
            print(f"[RAG Agent] LLM error: {e.to_dict()}")
            return None
        except Exception as e:
            print(f"[RAG Agent] Unexpected error: {e}")
            return None


# Global instance for backward compatibility
_rag_instance = None

def get_rag_instance(tenant_id: Optional[str] = None) -> TenantAwareRAG:
    """Get or create the RAG instance."""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = TenantAwareRAG(tenant_id)
    return _rag_instance


def run_rag_enhanced(
    query: str, 
    tenant_id: Optional[str] = None,
    use_llm: bool = False,
    context: Optional[str] = None
) -> dict[str, Any]:
    """Enhanced RAG with tenant isolation and optional LLM enhancement."""
    rag = get_rag_instance(tenant_id)
    
    # Update tenant if provided
    if tenant_id and rag.tenant_id != tenant_id:
        rag.tenant_id = tenant_id
        rag._index = None  # Force reindex with new tenant
    
    # Perform search with citations
    result = rag.search_with_citations(query)
    
    # Optionally enhance with LLM
    if use_llm and rag._llm_provider and result["citations"]:
        llm_answer = rag.llm_enhanced_answer(query, result["citations"], context)
        if llm_answer:
            result["llm_answer"] = llm_answer
            result["mode"] = "llm-enhanced"
        else:
            result["mode"] = "direct-rag"
    else:
        result["mode"] = "direct-rag"
    
    return result
