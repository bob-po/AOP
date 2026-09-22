import type { PiAgentHandle } from "../agent/pi-runtime.js";
import type { TaskStore } from "./task-store.js";
import type { DeployPanel } from "../ui/panel.js";
import type { RepairRecord, StepId, TaskRecord } from "../types.js";
import type { DockerRunner } from "../sandbox/docker-runner.js";
import { writeText } from "../tools/filesystem.js";
import { join } from "node:path";

export interface RepairLoopOptions {
  agent: PiAgentHandle;
  runner: DockerRunner;
  task: TaskRecord;
  store: TaskStore;
  panel: DeployPanel;
  maxRepairAttempts: number;
  failedStep: StepId;
  errorLog: string;
}

export interface RepairLoopResult {
  recovered: boolean;
  repairs: RepairRecord[];
  lastError?: string;
  buildOk?: boolean;
  startOk?: boolean;
  logs: string;
  containerId?: string;
  composeProject?: string;
}

export async function runRepairLoop(opts: RepairLoopOptions): Promise<RepairLoopResult> {
  const repairs: RepairRecord[] = [];
  let errorLog = opts.errorLog;
  let lastError = opts.errorLog;
  let logs = opts.errorLog;
  let containerId: string | undefined;
  let composeProject: string | undefined;

  for (let attempt = 1; attempt <= opts.maxRepairAttempts; attempt++) {
    opts.panel.repair(attempt, opts.maxRepairAttempts, "Diagnosing failure with Pi Agent...");
    opts.store.updateStatus(opts.task, "repairing");

    const advice = await opts.agent.repair(errorLog, attempt, opts.maxRepairAttempts);
    opts.panel.repair(attempt, opts.maxRepairAttempts, advice.action);
    opts.store.appendEvent(opts.task, `Repair: ${advice.action} (${advice.rootCause})`, "warn");

    writeText(
      join(opts.task.logsDir, `repair-${attempt}.log`),
      `ROOT_CAUSE: ${advice.rootCause}\nACTION: ${advice.action}\n\n${errorLog}`,
    );

    let buildOk = true;
    let startOk = true;

    if (advice.retryBuild || opts.failedStep === "build") {
      const build = await opts.runner.build();
      logs = build.logs;
      buildOk = build.success;
      if (!build.success) {
        errorLog = build.error || build.logs;
        lastError = errorLog;
      }
    }

    if (buildOk && (advice.retryStart || opts.failedStep === "start" || opts.failedStep === "health")) {
      const start = await opts.runner.start();
      logs = start.logs;
      startOk = start.success;
      containerId = start.containerId;
      composeProject = start.composeProject;
      if (!start.success) {
        errorLog = start.error || start.logs;
        lastError = errorLog;
      }
    }

    const success = buildOk && startOk;
    const record: RepairRecord = {
      attempt,
      at: new Date().toISOString(),
      step: opts.failedStep,
      errorSummary: lastError.slice(0, 500),
      action: advice.action,
      success,
    };
    repairs.push(record);
    opts.store.appendRepair(opts.task, record);

    if (success) {
      return {
        recovered: true,
        repairs,
        logs,
        containerId,
        composeProject,
        buildOk,
        startOk,
      };
    }

    // Refresh logs for next attempt
    errorLog = await opts.runner.collectLogs();
    if (!errorLog) errorLog = lastError;
  }

  return {
    recovered: false,
    repairs,
    lastError,
    logs,
    containerId,
    composeProject,
  };
}
