"""Test script to verify monitoring setup."""

import requests
import json
import time

def test_prometheus():
    """Test Prometheus endpoint."""
    try:
        response = requests.get("http://localhost:9090/-/healthy", timeout=5)
        if response.status_code == 200:
            print("✓ Prometheus is healthy")
            return True
        else:
            print(f"✗ Prometheus health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Prometheus connection failed: {e}")
        return False

def test_grafana():
    """Test Grafana endpoint."""
    try:
        response = requests.get("http://localhost:3001/api/health", timeout=5)
        if response.status_code == 200:
            print("✓ Grafana is healthy")
            return True
        else:
            print(f"✗ Grafana health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Grafana connection failed: {e}")
        return False

def test_alertmanager():
    """Test AlertManager endpoint."""
    try:
        response = requests.get("http://localhost:9093/-/healthy", timeout=5)
        if response.status_code == 200:
            print("✓ AlertManager is healthy")
            return True
        else:
            print(f"✗ AlertManager health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ AlertManager connection failed: {e}")
        return False

def test_webhook():
    """Test webhook endpoint."""
    try:
        response = requests.get("http://localhost:5000/", timeout=5)
        if response.status_code == 200:
            print("✓ Webhook service is running")
            return True
        else:
            print(f"✗ Webhook health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Webhook connection failed: {e}")
        return False

def test_orchestrator_metrics():
    """Test Orchestrator metrics endpoint."""
    try:
        response = requests.get("http://localhost:8090/metrics", timeout=5)
        if response.status_code == 200:
            print("✓ Orchestrator metrics endpoint is available")
            metrics = response.text
            if "aop_" in metrics:
                print("✓ Orchestrator metrics contain AOP metrics")
                return True
            else:
                print("✗ Orchestrator metrics don't contain AOP metrics")
                return False
        else:
            print(f"✗ Orchestrator metrics endpoint failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Orchestrator metrics connection failed: {e}")
        return False

def test_gateway_metrics():
    """Test Gateway metrics endpoint."""
    try:
        response = requests.get("http://localhost:8080/metrics", timeout=5)
        if response.status_code == 200:
            print("✓ Gateway metrics endpoint is available")
            return True
        else:
            print(f"✗ Gateway metrics endpoint failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Gateway metrics connection failed: {e}")
        return False

def test_prometheus_targets():
    """Test Prometheus targets."""
    try:
        response = requests.get("http://localhost:9090/api/v1/targets", timeout=5)
        if response.status_code == 200:
            data = response.json()
            targets = data.get('data', {}).get('activeTargets', [])
            print(f"✓ Prometheus has {len(targets)} targets configured")
            for target in targets:
                health = target.get('health', 'unknown')
                labels = target.get('labels', {})
                job = labels.get('job', 'unknown')
                print(f"  - {job}: {health}")
            return True
        else:
            print(f"✗ Prometheus targets API failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"✗ Prometheus targets check failed: {e}")
        return False

if __name__ == "__main__":
    print("Testing AOP Monitoring Setup")
    print("=" * 40)

    # Wait a moment for services to be ready
    print("Waiting for services to start...")
    time.sleep(5)

    results = []
    results.append(("Prometheus", test_prometheus()))
    results.append(("Grafana", test_grafana()))
    results.append(("AlertManager", test_alertmanager()))
    results.append(("Webhook", test_webhook()))
    results.append(("Orchestrator Metrics", test_orchestrator_metrics()))
    results.append(("Gateway Metrics", test_gateway_metrics()))
    results.append(("Prometheus Targets", test_prometheus_targets()))

    print("\n" + "=" * 40)
    print("Test Results Summary:")
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{name}: {status}")

    all_passed = all(result for _, result in results)
    print("\n" + "=" * 40)
    if all_passed:
        print("✓ All monitoring tests passed!")
    else:
        print("✗ Some monitoring tests failed. Please check the logs.")