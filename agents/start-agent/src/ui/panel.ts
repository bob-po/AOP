import chalk from "chalk";
import type { StepId, TaskRecord } from "../types.js";
import { DEPLOY_STEPS } from "../types.js";

export class DeployPanel {
  private agentLines: string[] = [];
  private repairLine?: string;
  private started = false;

  start(): void {
    this.started = true;
    console.log("");
    console.log(chalk.bold.cyan("DeployPilot"));
    console.log(chalk.dim("Powered by Pi Agent"));
    console.log("");
    this.render();
  }

  private statusIcon(status: string): string {
    switch (status) {
      case "done":
        return chalk.green("DONE");
      case "running":
        return chalk.yellow("RUNNING");
      case "failed":
        return chalk.red("FAILED");
      case "skipped":
        return chalk.dim("SKIPPED");
      default:
        return chalk.dim("PENDING");
    }
  }

  render(task?: TaskRecord): void {
    if (!this.started) return;
    const steps = task?.steps ?? DEPLOY_STEPS.map((s) => ({ ...s, status: "pending" as const }));
    for (let i = 0; i < steps.length; i++) {
      const step = steps[i];
      const idx = `[${i + 1}/${steps.length}]`;
      const label = step.label.padEnd(30, " ");
      console.log(`${chalk.dim(idx)} ${label} ${this.statusIcon(step.status)}`);
    }
    if (this.agentLines.length) {
      console.log("");
      for (const line of this.agentLines.slice(-5)) {
        console.log(chalk.magenta(`Agent: ${line}`));
      }
    }
    if (this.repairLine) {
      console.log(chalk.yellow(this.repairLine));
    }
    console.log("");
  }

  setStep(task: TaskRecord, id: StepId): void {
    const step = task.steps.find((s) => s.id === id);
    if (!step) return;
    const index = task.steps.findIndex((s) => s.id === id) + 1;
    console.log(
      `${chalk.dim(`[${index}/${task.steps.length}]`)} ${step.label.padEnd(30, " ")} ${this.statusIcon(step.status)}`,
    );
  }

  agent(message: string): void {
    const clean = message.replace(/\s+/g, " ").trim();
    if (!clean) return;
    this.agentLines.push(clean.slice(0, 200));
    console.log(chalk.magenta(`Agent: ${clean.slice(0, 200)}`));
  }

  repair(attempt: number, max: number, action: string): void {
    this.repairLine = `[Repair ${attempt}/${max}] ${action}`;
    console.log(chalk.yellow(this.repairLine));
  }

  success(info: {
    project: string;
    runtime: string;
    status: string;
    url?: string;
    logs: string;
    taskId: string;
  }): void {
    console.log("");
    console.log(chalk.bold.green("Deployment successful"));
    console.log("");
    console.log(`Project: ${info.project}`);
    console.log(`Runtime: ${info.runtime}`);
    console.log(`Status: ${info.status}`);
    if (info.url) console.log(`URL: ${info.url}`);
    console.log(`Task: ${info.taskId}`);
    console.log(`Logs: ${info.logs}`);
    console.log("");
  }

  failure(info: { project: string; error: string; logs: string; taskId: string }): void {
    console.log("");
    console.log(chalk.bold.red("Deployment failed"));
    console.log("");
    console.log(`Project: ${info.project}`);
    console.log(`Error: ${info.error}`);
    console.log(`Task: ${info.taskId}`);
    console.log(`Logs: ${info.logs}`);
    console.log("");
  }
}
