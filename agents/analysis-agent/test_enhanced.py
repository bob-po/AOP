"""Quick test for enhanced Analysis Agent (Phase 37.2)."""

import os
import sys

# Test direct import and execution
try:
    from context_enhanced import get_llm_provider, llm_analysis_with_metadata
    print("[PASS] Enhanced context module imported successfully")
    
    # Check LLM availability
    provider = get_llm_provider()
    if not provider:
        print("[INFO] LLM provider not available (set OPENAI_API_KEY to enable)")
        print("[INFO] Testing will skip LLM validation")
        print("[SUCCESS] Analysis Agent module structure valid (LLM validation requires API key)")
        sys.exit(0)
    
    print("[PASS] LLM provider initialized")
    
    # Test LLM analysis
    print("\nTesting LLM analysis...")
    goal = "Analyze the current state of AI agent orchestration platforms"
    upstream = {
        "search": "Recent developments in multi-agent systems include improved coordination protocols and enhanced tool calling capabilities.",
        "rag": "Knowledge base contains information about agent frameworks, orchestration patterns, and best practices.",
    }
    
    result = llm_analysis_with_metadata(goal, upstream)
    
    if not result:
        print("[FAIL] LLM analysis returned None")
        sys.exit(1)
    
    if not result.get("summary") or not result.get("insights"):
        print("[FAIL] Invalid response structure")
        sys.exit(1)
    
    print(f"[PASS] LLM analysis: {len(result.get('insights', []))} insights generated")
    print(f"Summary: {result.get('summary')[:200]}...")
    
    if "metadata" in result:
        print(f"Metadata: {result['metadata']}")
    
    print("\n[SUCCESS] Analysis Agent validation passed")
    
except ImportError as e:
    print(f"[FAIL] Import failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"[FAIL] Validation failed: {e}")
    sys.exit(1)
