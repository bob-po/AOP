import { join } from "node:path";
import { loadAppConfig } from "../config.js";
import { createPiAgent, verifyHealthFromPlan } from "../agent/pi-runtime.js";
import { prepareSource } from "../tools/git.js";
import { buildHeuristicPlan, inspectProject } from "../tools/project-inspector.js";
import { dockerAvailable, dockerDiagnostics } from "../tools/docker.js";
import { writeText } from "../tools/filesystem.js";
import { DockerRunner } from "../sandbox/docker-runner.js";
import { ensureWorkspaceLayout } from "../sandbox/workspace.js";
import { DeployPanel } from "../ui/panel.js";
import type { DeployInput, DeploymentResult, TaskRecord } from "../types.js";
import { runRepairLoop } from "./repair-loop.js";
import { allDone, markRunning, resumeFrom, setStepStatus } from "./state-machine.js";
import { TaskStore } from "./task-store.js";

function safeImageTag(name: string): string {
  const safe = name.toLowerCase().replace(/[^a-z0-9_-]/g, "-").replace(/^-+/, "") || "app";
  return `deploypilot/${safe}:latest`;
}

export class Orchestrator {
  constructor(
    private readonly store = new TaskStore(),
    private readonly panel = new DeployPanel(),
  ) {}

  async deploy(input: DeployInput): Promise<{ task: TaskRecord; result: DeploymentResult }> {
    const config = loadAppConfig();
    const maxRepair = input.maxRepairAttempts ?? config.maxRepairAttempts;

    let task: TaskRecord;
    if (input.resume && input.taskId) {
      task = this.store.require(input.taskId);
      this.store.updateStatus(task, "pending");
      this.store.appendEvent(task, "Resuming interrupted task", "info");
    } else {
      task = this.store.create({
        ...input,
        mode: input.mode ?? config.mode,
        maxRepairAttempts: maxRepair,
        memoryLimit: input.memoryLimit ?? config.memoryLimit,
        cpuLimit: input.cpuLimit ?? config.cpuLimit,
        model: input.model ?? config.model,
      });
    }

    this.panel.start();
    const startStep = input.resume ? resumeFrom(task) : "clone";

    const onSignal = () => {
      this.store.updateStatus(task, "interrupted");
      this.store.appendEvent(task, "Interrupted by signal", "warn");
      console.log(`\nInterrupted. Resume with: deploypilot resume ${task.id}\n`);
      process.exit(130);
    };
    process.once("SIGINT", onSignal);
    process.once("SIGTERM", onSignal);

    let runner: DockerRunner | undefined;
    let agent: Awaited<ReturnType<typeof createPiAgent>> | undefined;

    try {
      // 1. Clone / copy source
      if (shouldRun(task, "clone", startStep)) {
        markRunning(task, "clone");
        this.store.updateStatus(task, "cloning");
        this.store.save(task);
        this.panel.setStep(task, "clone");

        ensureWorkspaceLayout(task.workspaceDir);
        const prepared = await prepareSource(task.input.source, task.sourceDir);
        task.sourceDir = prepared.sourceDir;
        setStepStatus(task, "clone", "done");
        this.store.appendEvent(
          task,
          prepared.cloned ? `Cloned ${task.input.source}` : `Copied local source ${task.input.source}`,
        );
        this.store.save(task);
        this.panel.setStep(task, "clone");
      }

      // 2. Analyze
      if (shouldRun(task, "analyze", startStep)) {
        markRunning(task, "analyze");
        this.store.updateStatus(task, "analyzing");
        this.store.save(task);
        this.panel.setStep(task, "analyze");

        const project = inspectProject(task.sourceDir);
        task.project = project;
        writeText(join(task.workspaceDir, "artifacts", "project.json"), JSON.stringify(project, null, 2));
        setStepStatus(task, "analyze", "done");
        this.store.appendEvent(
          task,
          `Detected ${project.kind} project "${project.name}" (ports: ${project.ports.join(",") || "n/a"})`,
        );
        this.store.save(task);
        this.panel.setStep(task, "analyze");
      }

      if (!task.project) {
        throw new Error("Project analysis missing; cannot continue");
      }

      // 3. Plan via Pi Agent (fallback heuristic)
      if (shouldRun(task, "plan", startStep)) {
        markRunning(task, "plan");
        this.store.updateStatus(task, "planning");
        this.store.save(task);
        this.panel.setStep(task, "plan");

        agent = await createPiAgent({
          project: task.project,
          task,
          store: this.store,
          panel: this.panel,
          model: task.input.model,
        });

        if (!agent.available) {
          this.panel.agent(agent.reason || "Using heuristic planner (no model auth)");
          this.store.appendEvent(task, agent.reason || "heuristic planner", "warn");
        } else {
          this.panel.agent("Pi Agent online — generating deployment plan");
        }

        const plan = await agent.planDeployment();
        if (!plan.imageTag) plan.imageTag = safeImageTag(task.project.name);
        task.plan = plan;
        writeText(join(task.workspaceDir, "artifacts", "plan.json"), JSON.stringify(plan, null, 2));
        setStepStatus(task, "plan", "done");
        this.store.appendEvent(task, `Plan (${plan.generatedBy}): ${plan.summary}`);
        this.store.save(task);
        this.panel.setStep(task, "plan");
      } else if (!agent) {
        agent = await createPiAgent({
          project: task.project,
          task,
          store: this.store,
          panel: this.panel,
          model: task.input.model,
        });
      }

      if (!task.plan) {
        task.plan = buildHeuristicPlan(task.project, safeImageTag(task.project.name));
      }

      if (task.input.target?.startsWith("ssh://")) {
        throw new Error(
          "SSH remote target is planned for a later release. Use local Docker mode for MVP.",
        );
      }

      if (!(await dockerAvailable()) && (task.input.mode ?? config.mode) === "docker") {
        const detail = await dockerDiagnostics();
        throw new Error(
          `Docker daemon is required for mode=docker but is not reachable. ${detail}`,
        );
      }

      runner = new DockerRunner(task.project, task.plan, config, task.id);

      // 4. Prepare sandbox
      if (shouldRun(task, "prepare", startStep)) {
        markRunning(task, "prepare");
        this.store.updateStatus(task, "preparing");
        this.store.save(task);
        this.panel.setStep(task, "prepare");

        const prepared = await runner.prepare();
        if (!prepared.success) {
          setStepStatus(task, "prepare", "failed", prepared.error);
          this.store.save(task);
          throw new Error(prepared.error || "Prepare failed");
        }
        setStepStatus(task, "prepare", "done");
        this.store.appendEvent(task, "Sandbox prepared with resource limits");
        this.store.save(task);
        this.panel.setStep(task, "prepare");
      }

      // 5. Build
      let buildLogs = "";
      if (shouldRun(task, "build", startStep)) {
        markRunning(task, "build");
        this.store.updateStatus(task, "building");
        this.store.save(task);
        this.panel.setStep(task, "build");

        let build = await runner.build();
        buildLogs = build.logs;
        writeText(join(task.logsDir, "build.log"), buildLogs);

        if (!build.success) {
          this.panel.agent("Detected a build failure. Starting repair loop...");
          const repair = await runRepairLoop({
            agent: agent!,
            runner,
            task,
            store: this.store,
            panel: this.panel,
            maxRepairAttempts: maxRepair,
            failedStep: "build",
            errorLog: build.error || build.logs,
          });
          if (!repair.recovered) {
            setStepStatus(task, "build", "failed", repair.lastError);
            this.store.save(task);
            return this.finalize(task, {
              success: false,
              status: "failed",
              logsDir: task.logsDir,
              repairs: task.repairs,
              error: repair.lastError || "Build failed after repairs",
              runtime: task.plan.runtime,
            });
          }
          buildLogs = repair.logs;
        }

        setStepStatus(task, "build", "done");
        this.store.appendEvent(task, "Build completed");
        this.store.save(task);
        this.panel.setStep(task, "build");
      }

      // 6. Start
      let containerId: string | undefined;
      let composeProject: string | undefined;
      if (shouldRun(task, "start", startStep)) {
        markRunning(task, "start");
        this.store.updateStatus(task, "starting");
        this.store.save(task);
        this.panel.setStep(task, "start");

        let start = await runner.start();
        writeText(join(task.logsDir, "runtime.log"), start.logs);
        containerId = start.containerId;
        composeProject = start.composeProject;

        if (!start.success) {
          this.panel.agent("Detected a startup failure. Starting repair loop...");
          const repair = await runRepairLoop({
            agent: agent!,
            runner,
            task,
            store: this.store,
            panel: this.panel,
            maxRepairAttempts: maxRepair,
            failedStep: "start",
            errorLog: start.error || start.logs,
          });
          if (!repair.recovered) {
            setStepStatus(task, "start", "failed", repair.lastError);
            this.store.save(task);
            return this.finalize(task, {
              success: false,
              status: "failed",
              logsDir: task.logsDir,
              repairs: task.repairs,
              error: repair.lastError || "Start failed after repairs",
              runtime: task.plan.runtime,
              containerId: repair.containerId,
              composeProject: repair.composeProject,
            });
          }
          containerId = repair.containerId;
          composeProject = repair.composeProject;
          writeText(join(task.logsDir, "runtime.log"), repair.logs);
        }

        setStepStatus(task, "start", "done");
        this.store.appendEvent(task, "Services started");
        this.store.save(task);
        this.panel.setStep(task, "start");
      }

      // 7. Health check — must be real
      if (shouldRun(task, "health", startStep)) {
        markRunning(task, "health");
        this.store.updateStatus(task, "health_check");
        this.store.save(task);
        this.panel.setStep(task, "health");

        let health = await verifyHealthFromPlan(task.plan);
        writeText(
          join(task.logsDir, "health.log"),
          JSON.stringify(health, null, 2) + "\n" + (await runner.collectLogs()),
        );

        if (!health.ok) {
          this.panel.agent("Health check failed. Attempting repair...");
          const repair = await runRepairLoop({
            agent: agent!,
            runner,
            task,
            store: this.store,
            panel: this.panel,
            maxRepairAttempts: maxRepair,
            failedStep: "health",
            errorLog: health.detail + "\n" + (await runner.collectLogs()),
          });
          if (repair.recovered) {
            health = await verifyHealthFromPlan(task.plan);
            containerId = repair.containerId ?? containerId;
            composeProject = repair.composeProject ?? composeProject;
          }
          if (!health.ok) {
            setStepStatus(task, "health", "failed", health.detail);
            this.store.save(task);
            return this.finalize(task, {
              success: false,
              status: "unhealthy",
              url: health.url,
              logsDir: task.logsDir,
              repairs: task.repairs,
              error: health.detail,
              runtime: task.plan.runtime,
              containerId,
              composeProject,
            });
          }
        }

        setStepStatus(task, "health", "done");
        this.store.appendEvent(task, `Health OK: ${health.url} (${health.detail})`);
        this.store.save(task);
        this.panel.setStep(task, "health");

        return this.finalize(task, {
          success: true,
          status: "healthy",
          url: health.url,
          runtime:
            task.plan.runtime === "docker-compose"
              ? "Docker Compose"
              : task.plan.runtime === "docker"
                ? "Docker"
                : "Local",
          logsDir: task.logsDir,
          repairs: task.repairs,
          containerId,
          composeProject,
        });
      }

      // If resumed past health somehow
      if (allDone(task) && task.result) {
        return { task, result: task.result };
      }

      throw new Error("Deployment finished unexpectedly without health verification");
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      this.store.appendEvent(task, message, "error");
      return this.finalize(task, {
        success: false,
        status: "failed",
        logsDir: task.logsDir,
        repairs: task.repairs,
        error: message,
        runtime: task.plan?.runtime,
      });
    } finally {
      process.removeListener("SIGINT", onSignal);
      process.removeListener("SIGTERM", onSignal);
      agent?.dispose();
    }
  }

  private finalize(
    task: TaskRecord,
    result: DeploymentResult,
  ): { task: TaskRecord; result: DeploymentResult } {
    task.result = result;
    this.store.updateStatus(task, result.success ? "succeeded" : "failed");
    this.store.save(task);
    writeText(join(task.workspaceDir, "artifacts", "result.json"), JSON.stringify(result, null, 2));

    if (result.success) {
      this.panel.success({
        project: task.project?.name || "project",
        runtime: result.runtime || "unknown",
        status: "Healthy",
        url: result.url,
        logs: result.logsDir,
        taskId: task.id,
      });
    } else {
      this.panel.failure({
        project: task.project?.name || "project",
        error: result.error || "Unknown error",
        logs: result.logsDir,
        taskId: task.id,
      });
    }
    return { task, result };
  }
}

const ORDER = ["clone", "analyze", "plan", "prepare", "build", "start", "health"] as const;

function shouldRun(
  task: TaskRecord,
  step: (typeof ORDER)[number],
  startStep: (typeof ORDER)[number],
): boolean {
  const stepState = task.steps.find((s) => s.id === step)?.status;
  if (stepState === "done") return false;
  return ORDER.indexOf(step) >= ORDER.indexOf(startStep);
}

export async function deploy(input: DeployInput) {
  return new Orchestrator().deploy(input);
}
