import { Command } from "commander";
import chalk from "chalk";
import { deploy } from "../core/orchestrator.js";
import { TaskStore } from "../core/task-store.js";
import { loadAppConfig, loadUserConfig, saveUserConfig } from "../config.js";
import { dockerAvailable } from "../tools/docker.js";
import { readText, pathExists } from "../tools/filesystem.js";
import { join } from "node:path";
import { createInterface } from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";

async function prompt(question: string, fallback?: string): Promise<string> {
  const rl = createInterface({ input, output });
  const suffix = fallback ? ` (${fallback})` : "";
  const answer = (await rl.question(`${question}${suffix}: `)).trim();
  rl.close();
  return answer || fallback || "";
}

export function buildProgram(): Command {
  const program = new Command();
  program
    .name("deploypilot")
    .description("AI-powered deploy CLI powered by Pi Agent + Docker sandbox")
    .version("0.1.0");

  program
    .command("deploy")
    .description("Deploy a GitHub repository or local project")
    .argument("<source>", "GitHub URL or local directory")
    .option("--mode <mode>", "docker | local", "docker")
    .option("--target <target>", "local or ssh://user@host")
    .option("--model <model>", "Pi model spec, e.g. anthropic/claude-sonnet-4-5")
    .option("--max-repair <n>", "Max repair attempts", "3")
    .option("--memory <limit>", "Container memory limit", "512m")
    .option("--cpus <limit>", "Container CPU limit", "1.0")
    .action(async (source: string, opts) => {
      const result = await deploy({
        source,
        mode: opts.mode,
        target: opts.target,
        model: opts.model,
        maxRepairAttempts: Number(opts.maxRepair),
        memoryLimit: opts.memory,
        cpuLimit: opts.cpus,
      });
      process.exitCode = result.result.success ? 0 : 1;
    });

  program
    .command("status")
    .description("Show deployment task status")
    .argument("[taskId]", "Task id (omit to list recent)")
    .action((taskId?: string) => {
      const store = new TaskStore();
      if (!taskId) {
        const tasks = store.list().slice(0, 20);
        if (!tasks.length) {
          console.log("No tasks yet.");
          return;
        }
        for (const t of tasks) {
          console.log(
            `${t.id}  ${t.status.padEnd(12)}  ${t.project?.name || t.input.source}  ${t.updatedAt}`,
          );
        }
        return;
      }
      const task = store.require(taskId);
      console.log(JSON.stringify({
        id: task.id,
        status: task.status,
        source: task.input.source,
        project: task.project?.name,
        kind: task.project?.kind,
        result: task.result,
        steps: task.steps,
        repairs: task.repairs,
      }, null, 2));
    });

  program
    .command("logs")
    .description("Show deployment logs")
    .argument("<taskId>", "Task id")
    .option("--tail <n>", "Tail lines", "100")
    .action((taskId: string, opts) => {
      const store = new TaskStore();
      const task = store.require(taskId);
      const logFile = join(task.logsDir, "deploypilot.log");
      if (!pathExists(logFile)) {
        console.log("No logs found.");
        return;
      }
      const lines = readText(logFile).split(/\r?\n/);
      const tail = Number(opts.tail) || 100;
      console.log(lines.slice(-tail).join("\n"));
      console.log(chalk.dim(`\nLog dir: ${task.logsDir}`));
    });

  program
    .command("resume")
    .description("Resume an interrupted or failed task")
    .argument("<taskId>", "Task id")
    .action(async (taskId: string) => {
      const store = new TaskStore();
      const existing = store.require(taskId);
      const result = await deploy({
        ...existing.input,
        taskId,
        resume: true,
      });
      process.exitCode = result.result.success ? 0 : 1;
    });

  program
    .command("clean")
    .description("Clean deployment containers and task workspace")
    .argument("<taskId>", "Task id")
    .option("--keep-logs", "Keep log files on disk")
    .action(async (taskId: string, opts) => {
      const store = new TaskStore();
      const task = store.require(taskId);
      const { DockerRunner } = await import("../sandbox/docker-runner.js");
      const config = loadAppConfig();
      if (task.project && task.plan) {
        const runner = new DockerRunner(task.project, task.plan, config, task.id);
        await runner.cleanup();
      }
      if (!opts.keepLogs) {
        store.remove(taskId);
        console.log(`Removed task ${taskId}`);
      } else {
        store.updateStatus(task, "cleaned");
        console.log(`Cleaned runtime for ${taskId}; logs kept at ${task.logsDir}`);
      }
    });

  program
    .command("config")
    .description("Configure model and default limits")
    .action(async () => {
      const config = loadAppConfig();
      console.log(chalk.bold("DeployPilot configuration"));
      console.log(`Home: ${config.homeDir}`);
      const dockerOk = await dockerAvailable();
      console.log(`Docker: ${dockerOk ? chalk.green("available") : chalk.red("missing")}`);

      const current = loadUserConfig();
      const model = await prompt(
        "Default model (provider/model)",
        current.model || config.model || "anthropic/claude-sonnet-4-5",
      );
      const mode = (await prompt("Default mode", current.mode || config.mode || "docker")) as
        | "docker"
        | "local";
      const memoryLimit = await prompt("Memory limit", current.memoryLimit || config.memoryLimit);
      const cpuLimit = await prompt("CPU limit", current.cpuLimit || config.cpuLimit);
      const maxRepairAttempts = Number(
        await prompt("Max repair attempts", String(current.maxRepairAttempts || config.maxRepairAttempts)),
      );

      const saved = saveUserConfig({
        model,
        mode,
        memoryLimit,
        cpuLimit,
        maxRepairAttempts,
      });

      console.log("");
      console.log(chalk.green("Saved"), config.configPath);
      console.log(JSON.stringify(saved, null, 2));
      console.log("");
      console.log(
        chalk.dim(
          "Tip: set ANTHROPIC_API_KEY / OPENAI_API_KEY in the environment or ~/.deploypilot/.env",
        ),
      );
      console.log(
        chalk.dim(
          "Pi credentials are also read from ~/.deploypilot/pi-auth.json via ModelRuntime.",
        ),
      );
    });

  return program;
}
