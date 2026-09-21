"""Quick test for enhanced Search Agent (Phase 37.2)."""

import os
import sys
import asyncio

# Test direct import and execution
try:
    from search_enhanced import SearchAgentRuntime
    print("[PASS] Enhanced search module imported successfully")
    
    # Create runtime
    runtime = SearchAgentRuntime()
    print("[PASS] Search runtime created")
    
    # Test direct search
    print("\nTesting direct search...")
    result = runtime.execute_search("AI agents", use_llm=False)
    
    if result.get("source") == "mock-fallback":
        print("[FAIL] Search fell back to mock (not allowed)")
        sys.exit(1)
    
    if "error" in result:
        print(f"[FAIL] Search error: {result['error']}")
        sys.exit(1)
    
    print(f"[PASS] Direct search: {result.get('source')}, {len(result.get('results', []))} results")
    print(f"Summary: {result.get('summary')[:200]}...")
    
    # Check if LLM is available
    if runtime._llm_provider:
        print("\n[INFO] LLM provider available")
        print("To test LLM-enhanced search, set SEARCH_USE_LLM=true")
    else:
        print("\n[INFO] LLM provider not available (set OPENAI_API_KEY to enable)")
    
    print("\n[SUCCESS] Search Agent validation passed")
    
except ImportError as e:
    print(f"[FAIL] Import failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"[FAIL] Validation failed: {e}")
    sys.exit(1)
