"""Phase 37.2 E2E Validation Script for Transformed Agents.

This script validates that Search, Analysis, Report, and RAG agents can perform
real tasks with actual LLM calls and tool execution (no mock fallbacks).
"""

import os
import sys
import asyncio
import json
from datetime import datetime
from typing import Any, Dict

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../agents"))


class ValidationResult:
    """Result of agent validation."""
    def __init__(self, agent_name: str, success: bool, details: Dict[str, Any]):
        self.agent_name = agent_name
        self.success = success
        self.details = details
        self.timestamp = datetime.now().isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent_name,
            "success": self.success,
            "details": self.details,
            "timestamp": self.timestamp,
        }


async def validate_search_agent() -> ValidationResult:
    """Validate Search Agent with real search tools."""
    print("\n=== Validating Search Agent ===")
    
    try:
        # Test through direct agent file execution
        import subprocess
        result = subprocess.run(
            [sys.executable, "agents/search-agent/test_enhanced.py"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        validation_details = {
            "exit_code": result.returncode,
            "stdout": result.stdout[:500] if result.stdout else "",
            "stderr": result.stderr[:500] if result.stderr else "",
        }
        
        if result.returncode == 0:
            print("[PASS] Search Agent validation via direct test")
            return ValidationResult("search-agent", True, validation_details)
        else:
            print(f"[FAIL] Search Agent validation failed: {result.stderr[:200]}")
            return ValidationResult("search-agent", False, validation_details)
        
    except Exception as e:
        print(f"[FAIL] Search Agent validation error: {e}")
        return ValidationResult("search-agent", False, {"error": str(e)})


async def validate_analysis_agent() -> ValidationResult:
    """Validate Analysis Agent with real LLM calls."""
    print("\n=== Validating Analysis Agent ===")
    
    try:
        # Test through direct agent file execution
        import subprocess
        result = subprocess.run(
            [sys.executable, "agents/analysis-agent/test_enhanced.py"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        validation_details = {
            "exit_code": result.returncode,
            "stdout": result.stdout[:500] if result.stdout else "",
            "stderr": result.stderr[:500] if result.stderr else "",
        }
        
        if result.returncode == 0:
            print("[PASS] Analysis Agent validation via direct test")
            return ValidationResult("analysis-agent", True, validation_details)
        else:
            print(f"[FAIL] Analysis Agent validation failed: {result.stderr[:200]}")
            return ValidationResult("analysis-agent", False, validation_details)
        
    except Exception as e:
        print(f"[FAIL] Analysis Agent validation error: {e}")
        return ValidationResult("analysis-agent", False, {"error": str(e)})


async def validate_report_agent() -> ValidationResult:
    """Validate Report Agent with structured upstream data."""
    print("\n=== Validating Report Agent ===")
    
    try:
        # Test through direct agent file execution
        import subprocess
        result = subprocess.run(
            [sys.executable, "agents/report-agent/test_enhanced.py"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        validation_details = {
            "exit_code": result.returncode,
            "stdout": result.stdout[:500] if result.stdout else "",
            "stderr": result.stderr[:500] if result.stderr else "",
        }
        
        if result.returncode == 0:
            print("[PASS] Report Agent validation via direct test")
            return ValidationResult("report-agent", True, validation_details)
        else:
            print(f"[FAIL] Report Agent validation failed: {result.stderr[:200]}")
            return ValidationResult("report-agent", False, validation_details)
        
    except Exception as e:
        print(f"[FAIL] Report Agent validation error: {e}")
        return ValidationResult("report-agent", False, {"error": str(e)})


async def validate_rag_agent() -> ValidationResult:
    """Validate RAG Agent with tenant isolation and citation tracing."""
    print("\n=== Validating RAG Agent ===")
    
    try:
        # Test through direct agent file execution
        import subprocess
        result = subprocess.run(
            [sys.executable, "agents/rag-agent/test_enhanced.py"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        validation_details = {
            "exit_code": result.returncode,
            "stdout": result.stdout[:500] if result.stdout else "",
            "stderr": result.stderr[:500] if result.stderr else "",
        }
        
        if result.returncode == 0:
            print("[PASS] RAG Agent validation via direct test")
            return ValidationResult("rag-agent", True, validation_details)
        else:
            print(f"[FAIL] RAG Agent validation failed: {result.stderr[:200]}")
            return ValidationResult("rag-agent", False, validation_details)
        
    except Exception as e:
        print(f"[FAIL] RAG Agent validation error: {e}")
        return ValidationResult("rag-agent", False, {"error": str(e)})


async def main():
    """Run E2E validation for all transformed agents."""
    print("=" * 60)
    print("Phase 37.2 E2E Validation for Transformed Agents")
    print("=" * 60)
    
    # Check environment
    print("\nEnvironment check:")
    api_key_status = "[OK]" if os.getenv('OPENAI_API_KEY') else "[MISSING]"
    print(f"OPENAI_API_KEY: {api_key_status}")
    print(f"OPENAI_BASE_URL: {os.getenv('OPENAI_BASE_URL', 'Not set')}")
    print(f"OPENAI_MODEL: {os.getenv('OPENAI_MODEL', 'Not set')}")
    
    if not os.getenv("OPENAI_API_KEY"):
        print("\n[WARNING] OPENAI_API_KEY not set. Some validations may fail.")
        print("   Set OPENAI_API_KEY to enable full LLM validation.")
    
    # Run validations
    results = []
    
    results.append(await validate_search_agent())
    results.append(await validate_analysis_agent())
    results.append(await validate_report_agent())
    results.append(await validate_rag_agent())
    
    # Summary
    print("\n" + "=" * 60)
    print("Validation Summary")
    print("=" * 60)
    
    success_count = sum(1 for r in results if r.success)
    total_count = len(results)
    
    for result in results:
        status = "[PASS]" if result.success else "[FAIL]"
        print(f"{status} {result.agent_name}")
        if not result.success:
            print(f"   Error: {result.details.get('error', 'Unknown')}")
    
    print(f"\nTotal: {success_count}/{total_count} agents passed")
    
    # Save results
    output_file = "phase37_e2e_validation_results.json"
    with open(output_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total_agents": total_count,
            "passed_agents": success_count,
            "results": [r.to_dict() for r in results],
        }, f, indent=2)
    
    print(f"\nResults saved to: {output_file}")
    
    # Exit with appropriate code
    sys.exit(0 if success_count == total_count else 1)


if __name__ == "__main__":
    asyncio.run(main())
