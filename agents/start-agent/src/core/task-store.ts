import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { join } from "node:path";
import { nanoid } from "nanoid";
import { loadAppConfig } from "../config.js";
import type {
  DeployInput,
  DeployStep,
  RepairRecord,
  TaskRecord,
  TaskStatus,
} from "../types.js";
import { DEPLOY_STEPS } from "../types.js";

function initialSteps(): DeployStep[] {
  return DEPLOY_STEPS.map((s) => ({ id: s.id, label: s.label, status: "pending" }));
}

export class TaskStore {
  constructor(private readonly tasksDir = loadAppConfig().tasksDir) {
    mkdirSync(this.tasksDir, { recursive: true });
  }

  private taskDir(id: string): string {
    return join(this.tasksDir, id);
  }

  private metaPath(id: string): string {
    return join(this.taskDir(id), "task.json");
  }

  create(input: DeployInput): TaskRecord {
    const id = input.taskId || nanoid(10);
    const root = this.taskDir(id);
    const logsDir = join(root, "logs");
    const workspaceDir = join(root, "workspace");
    mkdirSync(logsDir, { recursive: true });
    mkdirSync(workspaceDir, { recursive: true });

    const now = new Date().toISOString();
    const task: TaskRecord = {
      id,
      createdAt: now,
      updatedAt: now,
      status: "pending",
      input,
      workspaceDir,
      sourceDir: join(workspaceDir, "src"),
      logsDir,
      steps: initialSteps(),
      repairs: [],
      events: [],
    };
    this.save(task);
    this.appendLog(id, `Task created for source: ${input.source}`);
    return task;
  }

  get(id: string): TaskRecord | undefined {
    const path = this.metaPath(id);
    if (!existsSync(path)) return undefined;
    return JSON.parse(readFileSync(path, "utf8")) as TaskRecord;
  }

  require(id: string): TaskRecord {
    const task = this.get(id);
    if (!task) throw new Error(`Task not found: ${id}`);
    return task;
  }

  list(): TaskRecord[] {
    const ids = readdirSync(this.tasksDir, { withFileTypes: true })
      .filter((d) => d.isDirectory())
      .map((d) => d.name);
    return ids
      .map((id) => this.get(id))
      .filter((t): t is TaskRecord => Boolean(t))
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }

  save(task: TaskRecord): void {
    task.updatedAt = new Date().toISOString();
    mkdirSync(this.taskDir(task.id), { recursive: true });
    writeFileSync(this.metaPath(task.id), JSON.stringify(task, null, 2), "utf8");
  }

  updateStatus(task: TaskRecord, status: TaskStatus): TaskRecord {
    task.status = status;
    this.save(task);
    this.appendLog(task.id, `Status -> ${status}`);
    return task;
  }

  appendEvent(
    task: TaskRecord,
    message: string,
    level: TaskRecord["events"][number]["level"] = "info",
  ): void {
    task.events.push({ at: new Date().toISOString(), message, level });
    this.save(task);
    this.appendLog(task.id, `[${level}] ${message}`);
  }

  appendRepair(task: TaskRecord, repair: RepairRecord): void {
    task.repairs.push(repair);
    this.save(task);
    this.appendLog(
      task.id,
      `Repair ${repair.attempt}: ${repair.action} (${repair.success ? "ok" : "fail"})`,
    );
  }

  appendLog(id: string, line: string): void {
    const logsDir = join(this.taskDir(id), "logs");
    mkdirSync(logsDir, { recursive: true });
    const stamp = new Date().toISOString();
    appendFileSync(join(logsDir, "deploypilot.log"), `${stamp} ${line}\n`, "utf8");
  }

  writeArtifact(id: string, name: string, content: string): string {
    const path = join(this.taskDir(id), name);
    writeFileSync(path, content, "utf8");
    return path;
  }

  remove(id: string): void {
    const dir = this.taskDir(id);
    if (existsSync(dir)) rmSync(dir, { recursive: true, force: true });
  }
}
