"""Execution worker: consume Redis Stream → route → A2A → unlock DAG."""

from __future__ import annotations

import argparse
import os
import socket
import threading
import time
import traceback
from typing import Any

from aggregator import Aggregator
from artifacts import ArtifactStore
from evaluation import EvaluationService
from executor import A2AExecutor
from memory import MemoryService
from observability import record_agent_call, record_task_finished
from router import AgentRouter, RouterError, normalize_endpoint
from sandbox import SandboxViolation, check_endpoint, check_skill
from scheduler import Scheduler
from streams import StreamClient

# OpenTelemetry tracing
try:
    from tracing import get_tracer, trace_operation, set_span_attribute, record_span_exception
    TRACING_AVAILABLE = True
    tracer = get_tracer("worker")
except ImportError:
    TRACING_AVAILABLE = False
    def get_tracer(name): return None
    def trace_operation(name, **kwargs): 
        from contextlib import contextmanager
        @contextmanager
        def dummy_context():
            yield None
        return dummy_context()
    def set_span_attribute(key, value): pass
    def record_span_exception(exception): pass
# Error handling imports
try:
    from error_handling import (
        CircuitBreakerOpenError,
        handle_a2a_error,
        RetryPolicy,
        with_retry,
        ErrorCategory,
        AOPError,
        get_circuit_breaker,
    )
    ERROR_HANDLING_AVAILABLE = True
except ImportError:
    ERROR_HANDLING_AVAILABLE = False
    # Fallback implementations
    def handle_a2a_error(error):
        return error
    RetryPolicy = None
    with_retry = None
    ErrorCategory = None
    AOPError = Exception
    CircuitBreakerOpenError = Exception  # type: ignore
    def get_circuit_breaker(service: str):  # type: ignore
        return None

# Enhanced retry policy for worker operations
if ERROR_HANDLING_AVAILABLE:
    WORKER_RETRY_POLICY = RetryPolicy(
        max_attempts=3,
        base_delay=1.0,
        max_delay=30.0,
        exponential_base=2.0,
        jitter=True
    )
else:
    WORKER_RETRY_POLICY = None

# attempt 1→2: 1s, 2→3: 3s, 3→fail handled before sleep for next
BACKOFF_SECONDS = {1: 1.0, 2: 3.0, 3: 10.0}
# Long-running node stale reclaim (seconds). 0 disables.
NODE_STALE_SECONDS = float(os.getenv("NODE_STALE_SECONDS", "900"))


class ExecutionWorker:
    def __init__(self, consumer_name: str | None = None):
        self.worker_id = consumer_name or f"executor-{socket.gethostname()}-{os.getpid()}"
        self.streams = StreamClient()
        self.scheduler = Scheduler()
        self.router = AgentRouter()
        self.executor = A2AExecutor(timeout=float(os.getenv("A2A_TIMEOUT", "60")))
        self.aggregator = Aggregator()
        self.artifacts = ArtifactStore()
        self.evaluations = EvaluationService()
        self.memory = MemoryService()
        self._last_stale_check = 0.0

    def run_forever(self) -> None:
        print(f"[worker] started consumer={self.worker_id}")
        while True:
            try:
                self._maybe_reclaim_stale()
                messages = self.streams.read_execution(self.worker_id, count=1, block_ms=2000)
                if not messages:
                    continue
                for msg_id, fields in messages:
                    try:
                        self.handle(fields)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[worker] handle error: {exc}")
                        traceback.print_exc()
                    finally:
                        self.streams.ack_execution(msg_id)
            except KeyboardInterrupt:
                print("[worker] stopping")
                break
            except Exception as exc:  # noqa: BLE001
                print(f"[worker] loop error: {exc}")
                time.sleep(1)

    def _execute_with_retry(self, endpoint: str, query: str, skill: str):
        """Execute A2A call with circuit breaker + retry."""
        def execute_a2a():
            result = self.executor.execute(endpoint, query, skill_id=skill)
            if not result.ok:
                error_msg = f"A2A execution failed with status {result.task.status.value}"
                raise handle_a2a_error(RuntimeError(error_msg))
            return result

        def guarded():
            breaker = get_circuit_breaker(f"a2a:{endpoint}") if get_circuit_breaker else None
            if breaker is not None:
                return breaker.call(execute_a2a)
            return execute_a2a()

        if with_retry:
            @with_retry(policy=WORKER_RETRY_POLICY)
            def retry_execute():
                return guarded()

            return retry_execute()
        return guarded()

    def _maybe_reclaim_stale(self) -> None:
        if NODE_STALE_SECONDS <= 0:
            return
        now = time.time()
        if now - self._last_stale_check < 30:
            return
        self._last_stale_check = now
        try:
            reclaimed = self.scheduler.reclaim_stale_nodes(stale_seconds=NODE_STALE_SECONDS)
            for job in reclaimed:
                self.streams.enqueue_execution(**job)
                print(
                    f"[worker] reclaimed stale node={job['node_key']} "
                    f"task={job['task_id'][:8]} attempt={job.get('attempt')}"
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] stale reclaim error: {exc}")

    def handle(self, fields: dict[str, str]) -> None:
        task_id = fields["task_id"]
        node_key = fields["node_key"]
        skill = fields["skill"]
        attempt = int(fields.get("attempt") or "1")
        exclude = {x for x in (fields.get("exclude_agent_ids") or "").split(",") if x}

        print(f"[worker] execute task={task_id} node={node_key} skill={skill} attempt={attempt}")

        # Start tracing span for this operation
        with trace_operation(
            "worker.handle",
            task_id=task_id,
            node_key=node_key,
            skill=skill,
            attempt=attempt
        ) as span:
            # Build query: goal + upstream outputs
            goal = self.scheduler.get_task_goal(task_id)
            query = self._compose_query(task_id, node_key, goal)
            
            # Add attributes to span
            if TRACING_AVAILABLE and span:
                set_span_attribute("worker.worker_id", self.worker_id)
                set_span_attribute("worker.goal_length", len(goal))

            try:
                routed = self.router.select(skill, exclude_agent_ids=exclude)
            except RouterError as exc:
                self._on_failure(
                    fields,
                    error=str(exc),
                    attempt=attempt,
                    agent_id=None,
                    exclude=exclude,
                )
                if TRACING_AVAILABLE:
                    record_span_exception(exc)
                return

            print(
                f"[worker] routed agent={routed.agent_key} score={routed.score} "
                f"breakdown={routed.score_breakdown}"
            )

            if TRACING_AVAILABLE and span:
                set_span_attribute("routing.agent_id", routed.agent_id)
                set_span_attribute("routing.score", routed.score)

            endpoint = normalize_endpoint(routed.endpoint)
            try:
                check_skill(skill)
                check_endpoint(endpoint)
            except SandboxViolation as exc:
                self._on_failure(
                    fields,
                    error=f"sandbox: {exc}",
                    attempt=attempt,
                    agent_id=routed.agent_id,
                    exclude=exclude | {routed.agent_id},
                )
                return

            claimed = self.scheduler.claim_running(task_id, node_key, routed.agent_id, attempt)
            if not claimed:
                print(f"[worker] skip claim node={node_key} (not ready/retrying)")
                return

            self.streams.publish_execution_event(
                "agent.task.started",
                {
                    "task_id": task_id,
                    "node_key": node_key,
                    "agent_id": routed.agent_id,
                    "attempt": attempt,
                },
            )

            started = time.time()
            try:
                with trace_operation(
                    "worker.execute_a2a", agent_id=routed.agent_id, endpoint=endpoint
                ) as exec_span:
                    if ERROR_HANDLING_AVAILABLE and WORKER_RETRY_POLICY:
                        result = self._execute_with_retry(endpoint, query, skill)
                    else:
                        result = self.executor.execute(endpoint, query, skill_id=skill)

                    if not result.ok:
                        raise RuntimeError(f"a2a status={result.task.status.value}")
                    latency_ms = int((time.time() - started) * 1000)

                    if TRACING_AVAILABLE and exec_span:
                        set_span_attribute("execution.latency_ms", latency_ms)
                        set_span_attribute(
                            "execution.artifact_count",
                            len(result.task.artifacts or []),
                        )
                refs = self.artifacts.persist_node_output(
                    task_id=task_id,
                    node_key=node_key,
                    text=result.text,
                    data=result.data,
                )
                output = {
                    "text": result.text,
                    "data": result.data,
                    "artifacts": [r.to_dict() for r in refs],
                    "agent": {
                        "id": routed.agent_id,
                        "key": routed.agent_key,
                        "endpoint": endpoint,
                    },
                    "a2a_task_id": result.task.id,
                }
                ready_jobs = self._with_task_lock(
                    task_id,
                    lambda: self.scheduler.mark_success(
                        task_id,
                        node_key,
                        output=output,
                        a2a_task_id=result.task.id,
                        latency_ms=latency_ms,
                    ),
                )
                self.streams.publish_execution_event(
                    "agent.task.completed",
                    {
                        "task_id": task_id,
                        "node_key": node_key,
                        "agent_id": routed.agent_id,
                        "latency_ms": latency_ms,
                        "artifact_count": len(refs),
                    },
                )
                try:
                    record_agent_call(
                        routed.agent_key,
                        status="success",
                        latency_seconds=latency_ms / 1000.0,
                    )
                except Exception:  # noqa: BLE001
                    pass
                print(
                    f"[worker] stored {len(refs)} artifacts for {node_key}: "
                    + ", ".join(r.uri for r in refs if r.name != "meta.json")
                )
                try:
                    self.memory.remember_node(
                        task_id,
                        node_key=node_key,
                        skill=skill,
                        text=result.text or "",
                        agent_id=routed.agent_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"[worker] memory write skipped: {exc}")
                for job in ready_jobs or []:
                    self.streams.enqueue_execution(**job)
                    print(f"[worker] enqueued downstream {job['node_key']}")

                task = self.scheduler.get_task(task_id)
                if task and task.get("status") == "waiting_for_user":
                    self.streams.publish_task_event(
                        "task.waiting_for_user",
                        {"task_id": task_id, "node_key": node_key},
                    )
                    print(f"[worker] task waiting_for_user {task_id} at {node_key}")
                elif task and task.get("status") == "completed":
                    result_json = self.aggregator.build_result(task_id)
                    self.streams.publish_task_event(
                        "task.completed",
                        {
                            "task_id": task_id,
                            "summary_len": len(result_json.get("summary") or ""),
                        },
                    )
                    print(f"[worker] task completed {task_id}")
                    try:
                        record_task_finished("completed")
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        if os.getenv("TENANT_MEMORY_PROMOTE", "1").lower() not in {
                            "0",
                            "false",
                            "no",
                            "off",
                        }:
                            promoted = self.memory.promote_task(task_id)
                            if promoted:
                                print(
                                    f"[worker] promoted {len(promoted)} tenant memories "
                                    f"from {task_id}"
                                )
                    except Exception as exc:  # noqa: BLE001
                        print(f"[worker] tenant memory promote skipped: {exc}")
                    self._auto_evaluate(task_id)

            except CircuitBreakerOpenError as exc:
                if TRACING_AVAILABLE:
                    record_span_exception(exc)
                self._on_failure(
                    fields,
                    error=str(exc),
                    attempt=attempt,
                    agent_id=routed.agent_id,
                    exclude=exclude | {routed.agent_id},
                )
            except Exception as exc:  # noqa: BLE001
                if TRACING_AVAILABLE:
                    record_span_exception(exc)
                self._on_failure(
                    fields,
                    error=str(exc),
                    attempt=attempt,
                    agent_id=routed.agent_id,
                    exclude=exclude | {routed.agent_id},
                )

    def _on_failure(
        self,
        fields: dict[str, str],
        *,
        error: str,
        attempt: int,
        agent_id: str | None,
        exclude: set[str],
    ) -> None:
        task_id = fields["task_id"]
        node_key = fields["node_key"]
        skill = fields["skill"]
        node_id = fields.get("node_id") or ""

        print(f"[worker] failure node={node_key} attempt={attempt}: {error}")
        try:
            record_agent_call(
                skill or (agent_id or "unknown"),
                status="failed",
                error_type=error.split(":", 1)[0][:48] or "error",
            )
        except Exception:  # noqa: BLE001
            pass
        decision = self.scheduler.mark_failure(
            task_id,
            node_key,
            error=error,
            attempt=attempt,
            agent_id=agent_id,
        )
        self.streams.publish_execution_event(
            "agent.task.failed",
            {
                "task_id": task_id,
                "node_key": node_key,
                "error": error,
                "attempt": attempt,
                "decision": decision.get("decision"),
            },
        )
        if decision.get("decision") == "retry":
            delay = BACKOFF_SECONDS.get(attempt, 10.0)
            next_attempt = int(decision["next_attempt"])
            print(
                f"[worker] retry node={node_key} next_attempt={next_attempt} "
                f"delay={delay}s exclude={sorted(exclude)}"
            )
            self.streams.enqueue_execution(
                task_id=task_id,
                node_id=node_id or decision.get("node_id") or "",
                node_key=node_key,
                skill=skill,
                attempt=next_attempt,
                exclude_agent_ids=sorted(exclude),
                delay_seconds=delay,
            )
        elif decision.get("decision") == "failed":
            try:
                record_task_finished("failed")
            except Exception:  # noqa: BLE001
                pass
            self._auto_evaluate(task_id)

    def _auto_evaluate(self, task_id: str) -> None:
        try:
            ev = self.evaluations.evaluate(task_id)
            self.streams.publish_task_event(
                "task.evaluated",
                {
                    "task_id": task_id,
                    "score": ev.get("score"),
                    "grade": ev.get("grade"),
                    "method": ev.get("method"),
                },
            )
            print(
                f"[worker] evaluated {task_id} grade={ev.get('grade')} score={ev.get('score')}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] evaluate skipped {task_id}: {exc}")

    def _compose_query(self, task_id: str, node_key: str, goal: str) -> str:
        task = self.scheduler.get_task(task_id)
        if not task:
            return goal
        parts = [f"User goal: {goal}", f"Current node: {node_key}"]
        try:
            mem = self.memory.compose_context(task_id)
            if mem:
                parts.append(mem)
        except Exception as exc:  # noqa: BLE001
            print(f"[worker] memory read skipped: {exc}")
        parts.append("Upstream results:")
        has_upstream = False
        for n in task.get("nodes") or []:
            if n.get("status") != "success":
                continue
            detail = self.scheduler.get_node(task_id, n["id"])
            if not detail:
                continue
            out = detail.get("output_json") or {}
            if isinstance(out, str):
                import json

                out = json.loads(out)
            if not isinstance(out, dict):
                continue

            text = out.get("text")
            # Prefer loading canonical text artifact from MinIO when available
            for art in out.get("artifacts") or []:
                if art.get("name") == "output.txt" and art.get("uri"):
                    try:
                        text = self.artifacts.get_text(art["uri"])
                    except Exception as exc:  # noqa: BLE001
                        print(f"[worker] warn load artifact {art['uri']}: {exc}")
                    break

            if text:
                has_upstream = True
                uri_hint = ""
                for art in out.get("artifacts") or []:
                    if art.get("name") == "output.json":
                        uri_hint = f"\n(artifact: {art.get('uri')})"
                        break
                parts.append(f"\n### {n['id']} ({n['skill']}){uri_hint}\n{text}")
        if not has_upstream and len(parts) <= 3:
            return goal
        parts.append("\nPlease continue based on the upstream results.")
        return "\n".join(parts)

    def _with_task_lock(self, task_id: str, fn):
        # Best-effort lock; proceed even if lock busy after short wait.
        for _ in range(20):
            if self.streams.acquire_task_lock(task_id, self.worker_id, ttl=30):
                try:
                    return fn()
                finally:
                    self.streams.release_task_lock(task_id, self.worker_id)
            time.sleep(0.1)
        return fn()


def main() -> None:
    parser = argparse.ArgumentParser(description="AOP execution worker")
    parser.add_argument("--consumer", default=None)
    args = parser.parse_args()

    # Expose prometheus_client metrics (agent call counters live here)
    try:
        from observability import start_metrics_server

        metrics_port = int(os.getenv("METRICS_PORT", "9091"))
        if start_metrics_server(port=metrics_port):
            print(f"[worker] metrics on :{metrics_port}/metrics")
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] metrics server skipped: {exc}")

    ExecutionWorker(consumer_name=args.consumer).run_forever()


if __name__ == "__main__":
    main()
