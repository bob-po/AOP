import type { DeployStep, StepId, StepStatus, TaskRecord } from "../types.js";

const FLOW: StepId[] = ["clone", "analyze", "plan", "prepare", "build", "start", "health"];

export function getStep(task: TaskRecord, id: StepId): DeployStep {
  const step = task.steps.find((s) => s.id === id);
  if (!step) throw new Error(`Unknown step: ${id}`);
  return step;
}

export function setStepStatus(
  task: TaskRecord,
  id: StepId,
  status: StepStatus,
  error?: string,
): DeployStep {
  const step = getStep(task, id);
  step.status = status;
  if (status === "running") step.startedAt = new Date().toISOString();
  if (status === "done" || status === "failed" || status === "skipped") {
    step.finishedAt = new Date().toISOString();
  }
  if (error) step.error = error;
  return step;
}

export function markRunning(task: TaskRecord, id: StepId): void {
  for (const step of task.steps) {
    if (step.id === id) {
      setStepStatus(task, id, "running");
    } else if (FLOW.indexOf(step.id) < FLOW.indexOf(id) && step.status === "pending") {
      setStepStatus(task, step.id, "skipped");
    }
  }
}

export function nextPendingStep(task: TaskRecord): StepId | undefined {
  for (const id of FLOW) {
    const step = getStep(task, id);
    if (step.status === "pending" || step.status === "failed" || step.status === "running") {
      return id;
    }
  }
  return undefined;
}

export function allDone(task: TaskRecord): boolean {
  return task.steps.every((s) => s.status === "done" || s.status === "skipped");
}

export function resumeFrom(task: TaskRecord): StepId {
  const failed = task.steps.find((s) => s.status === "failed" || s.status === "running");
  if (failed) {
    failed.status = "pending";
    failed.error = undefined;
    return failed.id;
  }
  return nextPendingStep(task) ?? "health";
}
