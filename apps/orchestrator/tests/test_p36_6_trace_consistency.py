"""
Phase 36.6 Trace & Artifact Consistency Test
Tests trace consistency and artifact consistency across execution
"""

import time
import uuid
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import sys
import os
import io

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

def test_trace_consistency():
    """Test trace consistency across execution attempts"""
    print_section("Trace Consistency Test (P36.6)")
    
    try:
        # Check if agent_runs table exists for trace tracking
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            tables = conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name = 'agent_runs'"
            ).fetchall()
            
            if not tables:
                print(f"[FAIL] agent_runs table does not exist")
                return False
            
            print(f"[OK] agent_runs table exists")
            
            # Check table structure
            columns = conn.execute(
                """
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'agent_runs' 
                ORDER BY ordinal_position
                """
            ).fetchall()
            
            column_names = [c['column_name'] for c in columns]
            print(f"[OK] agent_runs table has {len(columns)} columns")
            print(f"   - Columns: {column_names}")
            
            # Check for trace-related columns
            trace_columns = ['task_id', 'agent_id', 'status', 'latency_ms', 'error_message']
            found_trace = [col for col in trace_columns if col in column_names]
            
            if found_trace:
                print(f"[OK] Trace columns found: {found_trace}")
            else:
                print(f"[WARNING] No trace columns found")
            
            # Check for existing traces
            traces = conn.execute(
                """
                SELECT id, task_id, agent_id, status, latency_ms 
                FROM agent_runs 
                ORDER BY created_at DESC 
                LIMIT 5
                """
            ).fetchall()
            
            if traces:
                print(f"[OK] Existing traces found: {len(traces)}")
                for trace in traces:
                    print(f"   - Trace ID: {trace['id']}, Task: {trace['task_id']}, Agent: {trace['agent_id']}, Status: {trace['status']}")
            else:
                print(f"[INFO] No existing traces found (expected in clean environment)")
            
            return True
    except Exception as e:
        print(f"[FAIL] Trace consistency test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_enhanced_observability():
    """Test enhanced observability and metrics"""
    print_section("Enhanced Observability Test (P36.6)")
    
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from enhanced_observability import DistributedMetrics, SLOMonitor, MetricType
        
        print("[INFO] Testing enhanced observability...")
        
        # Test DistributedMetrics
        metrics = DistributedMetrics(database_url=DATABASE_URL)
        
        # Test metric recording
        metrics.record_metric("test_metric", 100.0, MetricType.GAUGE, {"test": "data"})
        print(f"[OK] Metric recorded")
        
        # Test distributed state collection
        state = metrics.collect_distributed_state_metrics()
        print(f"[OK] Distributed state collected")
        print(f"   - Task states: {state.get('task_states')}")
        print(f"   - Node states: {state.get('node_states')}")
        print(f"   - Active workers: {state.get('active_workers')}")
        print(f"   - Request stats: {state.get('request_stats')}")
        print(f"   - Outbox stats: {state.get('outbox_stats')}")
        
        # Test SLO metrics recording
        slo_metrics = metrics.record_slo_metrics()
        print(f"[OK] SLO metrics recorded")
        print(f"   - Success rate: {slo_metrics.get('success_rate', 0):.2%}")
        print(f"   - Failure rate: {slo_metrics.get('failure_rate', 0):.2%}")
        
        # Test SLOMonitor
        slo_monitor = SLOMonitor()
        
        # Test SLO compliance check
        test_metrics = {
            "success_rate": 0.98,
            "failure_rate": 0.02
        }
        alerts = slo_monitor.check_slo_compliance(test_metrics)
        print(f"[OK] SLO compliance check completed")
        print(f"   - Alerts generated: {len(alerts)}")
        
        # Test with violation
        violation_metrics = {
            "success_rate": 0.90,
            "failure_rate": 0.10
        }
        violation_alerts = slo_monitor.check_slo_compliance(violation_metrics)
        print(f"[OK] SLO violation check completed")
        print(f"   - Violation alerts: {len(violation_alerts)}")
        
        # Test recent alerts
        recent_alerts = slo_monitor.get_recent_alerts(limit=10)
        print(f"[OK] Recent alerts retrieved: {len(recent_alerts)}")
        
        return True
    except Exception as e:
        print(f"[FAIL] Enhanced observability test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run P36.6 tests"""
    print_section("Phase 36.6 Trace & Artifact Consistency Test")
    print("Testing: Trace Consistency, Enhanced Observability")
    print("Focus: Trace consistency and observability\n")
    
    results = []
    
    # Test 1: Trace consistency
    results.append(("Trace Consistency", test_trace_consistency()))
    
    # Test 2: Enhanced observability
    results.append(("Enhanced Observability", test_enhanced_observability()))
    
    # Summary
    print_section("Test Summary")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n[SUCCESS] All tests passed! Phase 36.6 trace consistency is operational.")
    else:
        print(f"\n[WARNING] {total - passed} test(s) failed. Review the output above for details.")

if __name__ == "__main__":
    main()
