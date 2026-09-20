"""
Phase 36.7 Chaos Engineering Test
Tests chaos engineering and fault injection capabilities
"""

import time
import uuid
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import sys
import os
import io
import traceback

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Configuration
DATABASE_URL = "postgresql://aop:aop@127.0.0.1:5432/aop"

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")

def test_chaos_engine_framework():
    """Test chaos engineering framework"""
    print_section("Chaos Engineering Framework Test (P36.7)")
    
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from chaos_engineering import ChaosEngine, FailureType
        
        print("[INFO] Testing chaos engineering framework...")
        
        # Test chaos engine initialization
        chaos = ChaosEngine()
        
        print(f"[OK] Chaos engine initialized")
        
        # Test fault types
        fault_types = [
            FailureType.NETWORK_DELAY,
            FailureType.AGENT_TIMEOUT,
            FailureType.AGENT_ERROR,
            FailureType.DATABASE_FAILURE,
            FailureType.HIGH_LATENCY,
            FailureType.DUPLICATE_REQUEST,
        ]
        
        print(f"[OK] Fault types available: {len(fault_types)}")
        for fault_type in fault_types:
            print(f"   - {fault_type.value}")
        
        return True
    except Exception as e:
        print(f"[FAIL] Chaos engineering framework test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_fault_injection_decorator():
    """Test fault injection decorator"""
    print_section("Fault Injection Decorator Test (P36.7)")
    
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from chaos_engineering import ChaosEngine, FailureType
        
        print("[INFO] Testing chaos engine fault injection...")
        
        chaos = ChaosEngine()
        chaos.enable()
        
        print(f"[OK] Chaos engine enabled")
        
        # Test network delay injection
        print("[INFO] Injecting network delay fault...")
        start = time.time()
        chaos.inject_network_delay(100)
        elapsed = time.time() - start
        
        if elapsed >= 0.1:  # 100ms delay
            print(f"[OK] Network delay injected: {elapsed:.2f}s")
        else:
            print(f"[FAIL] Network delay not injected properly: {elapsed:.2f}s")
            return False
        
        # Test agent error injection
        print("[INFO] Injecting agent error fault...")
        error = chaos.inject_agent_error("Test error")
        
        if isinstance(error, RuntimeError) and "Test error" in str(error):
            print(f"[OK] Agent error fault injected successfully")
        else:
            print(f"[FAIL] Agent error fault not injected properly")
            return False
        
        chaos.disable()
        print(f"[OK] Chaos engine disabled")
        
        return True
    except Exception as e:
        print(f"[FAIL] Fault injection decorator test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_stress_test():
    """Test stress test runner"""
    print_section("Stress Test Runner Test (P36.7)")
    
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from chaos_engineering import StressTestRunner
        
        print("[INFO] Testing stress test runner...")
        
        runner = StressTestRunner()
        
        print(f"[OK] Stress test runner initialized")
        
        # Test concurrent task creation simulation
        print("[INFO] Simulating concurrent task creation...")
        
        def simple_task(i):
            return f"task_{i}"
        
        result = runner.run_concurrent_tasks(
            task_count=10,
            concurrent_limit=5,
            task_func=simple_task
        )
        
        print(f"[OK] Concurrent task simulation completed")
        print(f"   - Task count: {result['task_count']}")
        print(f"   - Successful: {result['successful']}")
        print(f"   - Failed: {result['failed']}")
        print(f"   - Duration: {result['duration']:.2f}s")
        print(f"   - Throughput: {result['throughput']:.2f} tasks/s")
        
        # Test results summary
        summary = runner.get_results_summary()
        
        if summary:
            print(f"[OK] Results summary collected")
            print(f"   - Total tests: {summary.get('total_tests', 0)}")
        
        return True
    except Exception as e:
        print(f"[FAIL] Stress test runner test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run P36.7 tests"""
    print_section("Phase 36.7 Chaos Engineering Test")
    print("Testing: Chaos Engineering Framework, Fault Injection, Stress Testing")
    print("Focus: Fault injection and chaos engineering capabilities\n")
    
    results = []
    
    # Test 1: Chaos engineering framework
    results.append(("Chaos Engineering Framework", test_chaos_engine_framework()))
    
    # Test 2: Fault injection decorator
    results.append(("Fault Injection Decorator", test_fault_injection_decorator()))
    
    # Test 3: Stress test runner
    results.append(("Stress Test Runner", test_stress_test()))
    
    # Summary
    print_section("Test Summary")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n[SUCCESS] All tests passed! Phase 36.7 chaos engineering is operational.")
    else:
        print(f"\n[WARNING] {total - passed} test(s) failed. Review the output above for details.")

if __name__ == "__main__":
    main()
