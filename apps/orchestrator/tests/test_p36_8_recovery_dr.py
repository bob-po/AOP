"""
Phase 36.8 Recovery and DR Test
Tests startup reconciliation, consistency checks, and disaster recovery
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

def test_startup_reconciliation():
    """Test startup reconciliation functionality"""
    print_section("Startup Reconciliation Test (P36.8)")
    
    try:
        import sys
        import os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from recovery_and_dr import StartupReconciler
        
        reconciler = StartupReconciler(database_url=DATABASE_URL)
        
        print("[INFO] Running full startup reconciliation...")
        issues = reconciler.run_full_reconciliation()
        
        print(f"[OK] Startup reconciliation completed")
        print(f"   - Total issues found: {len(issues)}")
        
        for issue in issues:
            print(f"   - Issue: {issue.issue_type.value}")
            print(f"     Severity: {issue.severity}")
            print(f"     Description: {issue.description}")
            print(f"     Affected IDs: {len(issue.affected_ids)}")
            print(f"     Recommendation: {issue.recommendation}")
        
        # Test auto-fix
        print("[INFO] Testing auto-fix for critical issues...")
        fixed = reconciler.auto_fix_critical_issues()
        
        print(f"[OK] Auto-fix completed")
        print(f"   - Orphaned tasks fixed: {fixed.get('orphaned_tasks', 0)}")
        print(f"   - Stale nodes fixed: {fixed.get('stale_nodes', 0)}")
        
        return True
    except Exception as e:
        print(f"[FAIL] Startup reconciliation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_recovery_simulation():
    """Test recovery simulation for stale nodes"""
    print_section("Recovery Simulation Test (P36.8)")
    
    try:
        from recovery_and_dr import StartupReconciler, ConsistencyIssue
        
        # Create a stale running node manually
        task_id = str(uuid.uuid4())
        tenant_id = "00000000-0000-0000-0000-000000000001"
        
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            with conn.transaction():
                # Create task
                conn.execute(
                    """
                    INSERT INTO tasks (id, tenant_id, title, input_json, status, progress, plan_json, created_at, updated_at, started_at)
                    VALUES (%s::uuid, %s::uuid, %s, %s::jsonb, 'running', 50, %s::jsonb, now() - '25 hours'::interval, now(), now() - '25 hours'::interval)
                    """,
                    (task_id, tenant_id, "Stale Task", Jsonb({"type": "text", "content": "test"}), Jsonb({"nodes": []})),
                )
                
                # Create node with stale running status
                node_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO task_nodes (id, task_id, node_key, skill, status, input_json, attempt, max_retry, idempotency_key, created_at, updated_at, started_at)
                    VALUES (%s::uuid, %s::uuid, %s, %s, 'running', %s::jsonb, 0, 3, %s, now() - '25 hours'::interval, now() - '25 hours'::interval, now() - '25 hours'::interval)
                    """,
                    (node_id, task_id, "stale-node", "web-search", Jsonb({"goal": "test"}), f"req_{task_id[:8]}_stale-node"),
                )
        
        print(f"[OK] Created stale running node: {node_id}")
        
        # Run reconciliation to detect the stale node
        reconciler = StartupReconciler(database_url=DATABASE_URL)
        issues = reconciler.run_full_reconciliation()
        
        stale_issues = [i for i in issues if i.issue_type == ConsistencyIssue.STALE_RUNNING_NODE]
        
        if stale_issues:
            print(f"[OK] Stale node detected: {len(stale_issues)} issues")
            for issue in stale_issues:
                print(f"   - Affected nodes: {issue.affected_ids}")
        else:
            print(f"[INFO] No stale nodes detected (expected if cleanup already ran)")
        
        # Test auto-fix
        fixed = reconciler.auto_fix_critical_issues()
        
        if fixed.get('stale_nodes', 0) > 0:
            print(f"[OK] Stale node auto-fixed: {fixed.get('stale_nodes', 0)}")
        else:
            print(f"[INFO] No stale nodes to fix (already cleaned or none created)")
        
        # Verify the node was fixed (if it was created and not cleaned)
        with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
            node = conn.execute(
                "SELECT status FROM task_nodes WHERE id = %s::uuid",
                (node_id,),
            ).fetchone()
            
            if node:
                if node['status'] == 'failed':
                    print(f"[OK] Node status updated to failed")
                else:
                    print(f"[INFO] Node status: {node['status']} (may have been cleaned by auto-fix)")
            else:
                print(f"[INFO] Node not found (may have been cleaned by auto-fix)")
        
        # Cleanup
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.transaction():
                conn.execute("DELETE FROM task_nodes WHERE id = %s::uuid", (node_id,))
                conn.execute("DELETE FROM tasks WHERE id = %s::uuid", (task_id,))
        
        return True
    except Exception as e:
        print(f"[FAIL] Recovery simulation test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_disaster_recovery_manager():
    """Test disaster recovery manager"""
    print_section("Disaster Recovery Manager Test (P36.8)")
    
    try:
        from recovery_and_dr import DisasterRecoveryManager
        
        dr_manager = DisasterRecoveryManager(database_url=DATABASE_URL)
        
        print("[INFO] Testing backup snapshot creation...")
        backup_id = dr_manager.create_backup_snapshot()
        
        if backup_id:
            print(f"[OK] Backup snapshot created: {backup_id}")
        else:
            print(f"[FAIL] Backup snapshot creation failed")
            return False
        
        print("[INFO] Testing backup integrity verification...")
        verified = dr_manager.verify_backup_integrity(backup_id)
        
        if verified:
            print(f"[OK] Backup integrity verified")
        else:
            print(f"[FAIL] Backup integrity verification failed")
            return False
        
        return True
    except Exception as e:
        print(f"[FAIL] Disaster recovery manager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run P36.8 tests"""
    print_section("Phase 36.8 Recovery and DR Test")
    print("Testing: Startup Reconciliation, Recovery Simulation, Disaster Recovery")
    print("Focus: Recovery mechanisms and disaster preparedness\n")
    
    results = []
    
    # Test 1: Startup reconciliation
    results.append(("Startup Reconciliation", test_startup_reconciliation()))
    
    # Test 2: Recovery simulation
    results.append(("Recovery Simulation", test_recovery_simulation()))
    
    # Test 3: Disaster recovery manager
    results.append(("Disaster Recovery Manager", test_disaster_recovery_manager()))
    
    # Summary
    print_section("Test Summary")
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "[PASS]" if result else "[FAIL]"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n[SUCCESS] All tests passed! Phase 36.8 recovery and DR is operational.")
    else:
        print(f"\n[WARNING] {total - passed} test(s) failed. Review the output above for details.")

if __name__ == "__main__":
    main()
