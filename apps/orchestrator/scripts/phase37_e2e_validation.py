#!/usr/bin/env python3
"""E2E validation for harness virtual agents (specialty agents retired)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class ValidationResult:
    agent_name: str
    success: bool
    details: dict

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "success": self.success,
            "details": self.details,
        }


def validate_harness_unit_tests() -> ValidationResult:
    print("\n=== Validating harness unit tests ===")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "packages/agent-runtime/tests/test_harness_adapter.py",
            "packages/agent-runtime/tests/test_claude_cli_runner.py",
            "packages/agent-runtime/tests/test_pi_cli_runner.py",
            "packages/agent-runtime/tests/test_deepseek_runner.py",
            "agents/harness-agent/tests/test_profiles.py",
            "-q",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    details = {
        "exit_code": result.returncode,
        "stdout": (result.stdout or "")[:500],
        "stderr": (result.stderr or "")[:500],
    }
    ok = result.returncode == 0
    print(("[PASS]" if ok else "[FAIL]") + " harness unit tests")
    return ValidationResult("harness-runtime", ok, details)


def validate_profiles() -> ValidationResult:
    print("\n=== Validating harness profile cards ===")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "agents/harness-agent/tests/test_profiles.py", "-q"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    details = {
        "exit_code": result.returncode,
        "stdout": (result.stdout or "")[:500],
        "stderr": (result.stderr or "")[:500],
    }
    ok = result.returncode == 0
    print(("[PASS]" if ok else "[FAIL]") + " harness profiles")
    return ValidationResult("harness-profiles", ok, details)


def main() -> int:
    print("=" * 60)
    print("Harness Agent E2E Validation")
    print("=" * 60)
    results = [validate_harness_unit_tests(), validate_profiles()]
    success_count = sum(1 for r in results if r.success)
    total_count = len(results)
    print(f"\nTotal: {success_count}/{total_count} checks passed")
    out_dir = Path(__file__).resolve().parents[3] / "docs" / "phases" / "phase-37"
    out_dir.mkdir(parents=True, exist_ok=True)
    output_file = out_dir / "e2e-validation-results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "total_agents": total_count,
                "passed_agents": success_count,
                "results": [r.to_dict() for r in results],
            },
            f,
            indent=2,
        )
    print(f"Results saved to: {output_file}")
    return 0 if success_count == total_count else 1


if __name__ == "__main__":
    raise SystemExit(main())
