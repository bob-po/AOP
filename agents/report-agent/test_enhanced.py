"""Quick test for enhanced Report Agent (Phase 37.2)."""

import os
import sys

# Test direct import and execution
try:
    from context_enhanced import get_llm_provider, llm_report_with_metadata
    print("[PASS] Enhanced context module imported successfully")
    
    # Check LLM availability
    provider = get_llm_provider()
    if not provider:
        print("[INFO] LLM provider not available (set OPENAI_API_KEY to enable)")
        print("[INFO] Testing will skip LLM validation")
        print("[SUCCESS] Report Agent module structure valid (LLM validation requires API key)")
        sys.exit(0)
    
    print("[PASS] LLM provider initialized")
    
    # Test LLM report generation
    print("\nTesting LLM report generation...")
    goal = "Generate a comprehensive report on AI agent orchestration"
    upstream = {
        "search": "Search results show growing interest in multi-agent systems with key players including AutoGen, LangGraph, and AOP.",
        "analysis": "Analysis reveals that orchestration platforms need to address scalability, fault tolerance, and observability.",
        "rag": "Knowledge base indicates that successful implementations require proper agent lifecycle management and clear communication protocols.",
    }
    
    report = llm_report_with_metadata(goal, upstream)
    
    if not report:
        print("[FAIL] LLM report generation returned None")
        sys.exit(1)
    
    if len(report) < 100:
        print("[FAIL] Report too short")
        sys.exit(1)
    
    print(f"[PASS] Generated {len(report)} character report")
    print(f"Contains markdown: {'#' in report or '##' in report}")
    print(f"Report preview: {report[:200]}...")
    
    print("\n[SUCCESS] Report Agent validation passed")
    
except ImportError as e:
    print(f"[FAIL] Import failed: {e}")
    sys.exit(1)
except Exception as e:
    print(f"[FAIL] Validation failed: {e}")
    sys.exit(1)
