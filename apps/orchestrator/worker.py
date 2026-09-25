"""Execution worker: thin entrypoint over ExecutionEngine."""

from __future__ import annotations

import argparse
import os

from executor.engine import ExecutionEngine

# Backward-compatible alias
ExecutionWorker = ExecutionEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="AOP execution worker")
    parser.add_argument("--consumer", default=None)
    args = parser.parse_args()

    try:
        from observability import start_metrics_server

        metrics_port = int(os.getenv("METRICS_PORT", "9091"))
        if start_metrics_server(port=metrics_port):
            print(f"[worker] metrics on :{metrics_port}/metrics")
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] metrics server skipped: {exc}")

    try:
        from error_handling import reset_circuit_breakers

        reset_circuit_breakers()
        print("[worker] circuit breakers reset")
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] circuit breaker reset skipped: {exc}")

    ExecutionEngine(consumer_name=args.consumer).run_forever()


if __name__ == "__main__":
    main()
