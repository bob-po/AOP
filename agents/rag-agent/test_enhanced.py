"""Quick test for enhanced RAG Agent (Phase 37.2)."""

import os
import sys

# Test direct import and execution
try:
    from rag_enhanced import run_rag_enhanced, get_rag_instance
    print("[PASS] Enhanced RAG module imported successfully")
    
    # Test basic RAG
    print("\nTesting RAG with tenant isolation...")
    result = run_rag_enhanced(
        "What are the key components of agent orchestration?",
        tenant_id="default",
        use_llm=False
    )
    
    print(f"[INFO] RAG search: {len(result.get('citations', []))} citations")
    print(f"[INFO] Tenant: {result.get('tenant_id')}")
    print(f"[INFO] Method: {result.get('method')}")
    print(f"[INFO] Corpus size: {result.get('corpus_size')}")
    
    # Check LLM availability
    rag_instance = get_rag_instance()
    if rag_instance._llm_provider:
        print("[INFO] LLM provider available (set RAG_USE_LLM=true to test)")
    else:
        print("[INFO] LLM provider not available (set OPENAI_API_KEY to enable)")
    
    print("\n[SUCCESS] RAG Agent validation passed")
    
except ImportError as e:
    print(f"[FAIL] Import failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"[FAIL] Validation failed: {e}")
    sys.exit(1)
