"""ExecutionEngine: consume Redis Stream → route → A2A → unlock DAG."""

from __future__ import annotations

import os
import socket
import time
import traceback
from typing import Any

from aggregator import Aggregator
from artifacts import ArtifactStore
from evaluation import EvaluationService
from . import A2AExecutor
from memory import MemoryService
from observability import record_agent_call, record_task_finished
from router import RouterError, normalize_endpoint
from router.engine import RoutingEngine
from sandbox import SandboxViolation, check_endpoint, check_skill
from scheduler import Scheduler
from streams import StreamClient

# OpenTelemetry tracing
try:
    from tracing import get_tracer, trace_operation, set_span_attribute, record_span_exception
    TRACING_AVAILABLE = True
    tracer = get_tracer("execution")
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
        AOPError,
        get_circuit_breaker,
    )
    ERROR_HANDLING_AVAILABLE = True
except ImportError:
    ERROR_HANDLING_AVAILABLE = False
    CircuitBreakerOpenError = Exception  # type: ignore
    handle_a2a_error = lambda e: e
    RetryPolicy = None
    with_retry = None
    AOPError = Exception
    def get_circuit_breaker(service: str):  # type: ignore
        return None

# Enhanced failure handling imports (P36.3)
try:
    from enhanced_failure_handling import (
        ErrorCategory as EnhancedErrorCategory,
        RecoveryStrategy,
        FailureContext,
        classify_error_module as classify_error,
        determine_recovery_strategy_module as determine_recovery_strategy,
    )
    ENHANCED_FAILURE_HANDLING_AVAILABLE = True
except ImportError:
    ENHANCED_FAILURE_HANDLING_AVAILABLE = False
    EnhancedErrorCategory = None
    RecoveryStrategy = None
    FailureContext = None
    classify_error = lambda e: "unknown"
    determine_recovery_strategy = lambda ec, ma: "retry"

# Request tracking for P36.1 idempotency (lazy import to avoid circular dependency)
REQUEST_TRACKING_AVAILABLE = False

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


class ExecutionEngine:
    """Execution pipeline for a single worker process / consumer."""

    def __init__(self, consumer_name: str | None = None):
        self.worker_id = consumer_name or f"executor-{socket.gethostname()}-{os.getpid()}"
        self.streams = StreamClient()
        self.scheduler = Scheduler()
        self.routing = RoutingEngine()
        self.router = self.routing.router
        self.executor = A2AExecutor(timeout=float(os.getenv("A2A_TIMEOUT", "60")))
        self.aggregator = Aggregator()
        self.artifacts = ArtifactStore()
        self.evaluations = EvaluationService()
        self.memory = MemoryService()
        self._last_stale_check = 0.0
        self._request_tracking_service = None  # Lazy-loaded

    def _get_request_tracking_service(self):
        """Lazy import of request tracking service."""
        if self._request_tracking_service is None:
            try:
                from request_tracking import get_request_tracking_service
                self._request_tracking_service = get_request_tracking_service()
            except ImportError:
                self._request_tracking_service = None
        return self._request_tracking_service

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

    def _execute_with_retry(self, endpoint: str, query: str, skill: str, idempotency_key: str | None = None):
        """Execute A2A call with circuit breaker + retry."""
        def execute_a2a():
            result = self.executor.execute(endpoint, query, skill_id=skill, idempotency_key=idempotency_key)
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
                routed = self.routing.select(skill, exclude_agent_ids=exclude)
            except RouterError as exc:
                self._on_failure(
                    fields,
                    error=str(exc),
                    attempt=attempt,
                    agent_id=None,
                    exclude=exclude,
                    idempotency_key=None,  # Not generated yet
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
                    idempotency_key=None,  # Not generated yet
                )
                return

            claimed = self.scheduler.claim_running(task_id, node_key, routed.agent_id, attempt)
            if not claimed:
                print(f"[worker] skip claim node={node_key} (not ready/retrying)")
                return

            # P36.1: Get or generate stable idempotency key for this node
            idempotency_key = self.scheduler.get_node_idempotency_key(task_id, node_key)
            if not idempotency_key:
                # Fallback for nodes created before migration
                idempotency_key = f"req_{task_id[:8]}_{node_key}"
            
            # P36.1: Track the request before execution
            tracking_service = self._get_request_tracking_service()
            if tracking_service:
                try:
                    # Get node_id from scheduler
                    node_info = self.scheduler.get_node_info(task_id, node_key)
                    node_id = node_info.get("id") if node_info else str(uuid.uuid4())
                    
                    tracking_service.track_request(
                        idempotency_key,
                        task_id,
                        node_id,
                        routed.agent_id,
                        {"query": query, "skill": skill, "attempt": attempt},
                    )
                    tracking_service.mark_request_running(idempotency_key)
                except Exception as e:
                    print(f"[worker] request tracking error: {e}")

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
                        result = self._execute_with_retry(endpoint, query, skill, idempotency_key=idempotency_key)
                    else:
                        result = self.executor.execute(endpoint, query, skill_id=skill, idempotency_key=idempotency_key)

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
                
                # P36.1: Mark request as completed
                if tracking_service:
                    try:
                        tracking_service.mark_request_completed(idempotency_key, output)
                    except Exception as e:
                        print(f"[worker] request completion tracking error: {e}")
                
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
                    idempotency_key=idempotency_key,
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
                    idempotency_key=idempotency_key,
                )

    def _on_failure(
        self,
        fields: dict[str, str],
        *,
        error: str,
        attempt: int,
        agent_id: str | None,
        exclude: set[str],
        idempotency_key: str | None = None,
    ) -> None:
        task_id = fields["task_id"]
        node_key = fields["node_key"]
        skill = fields["skill"]
        node_id = fields.get("node_id") or ""

        print(f"[worker] failure node={node_key} attempt={attempt}: {error}")
        
        # P36.3: Enhanced error classification
        if ENHANCED_FAILURE_HANDLING_AVAILABLE:
            try:
                error_category = classify_error(error)
                recovery_strategy = determine_recovery_strategy(error_category)
                print(f"[worker] error classification: {error_category.value}, strategy: {recovery_strategy.value}")
            except Exception as e:
                print(f"[worker] enhanced failure handling error: {e}")
        
        # P36.1: Mark request as failed or unknown (P1-006)
        tracking_service = self._get_request_tracking_service()
        if tracking_service and idempotency_key:
            try:
                # Mark as unknown on timeout, otherwise failed
                if "timeout" in error.lower():
                    tracking_service.mark_request_unknown(idempotency_key, reason=error)
                else:
                    tracking_service.mark_request_failed(idempotency_key, error)
            except Exception as e:
                print(f"[worker] request failure tracking error: {e}")
        
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
