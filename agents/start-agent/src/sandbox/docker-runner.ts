import { dirname, join } from "node:path";
import { writeText } from "../tools/filesystem.js";
import {
  composeDown,
  composeLogs,
  composeUp,
  dockerAvailable,
  dockerBuild,
  dockerInspectRunning,
  dockerLogs,
  dockerRm,
  dockerRun,
  freeDeployPilotPort,
  listPublishedHostPorts,
  pickHostPort,
} from "../tools/docker.js";
import type { AppConfig } from "../types.js";
import type { DeployPlan, ProjectInfo } from "../types.js";
import { ensureGeneratedCompose, ensureGeneratedDockerfile } from "./workspace.js";

export interface SandboxDeployResult {
  success: boolean;
  runtime: string;
  containerId?: string;
  composeProject?: string;
  logs: string;
  error?: string;
  phase: "prepare" | "build" | "start";
}

export class DockerRunner {
  constructor(
    private readonly project: ProjectInfo,
    private readonly plan: DeployPlan,
    private readonly config: AppConfig,
    private readonly taskId: string,
  ) {}

  containerName(): string {
    return `deploypilot-${this.taskId}`.toLowerCase().replace(/[^a-z0-9_-]/g, "-");
  }

  composeProject(): string {
    return `dp${this.taskId}`.toLowerCase().replace(/[^a-z0-9]/g, "").slice(0, 20);
  }

  async prepare(): Promise<SandboxDeployResult> {
    if (!(await dockerAvailable())) {
      return {
        success: false,
        runtime: "none",
        logs: "",
        error: "Docker is not available. Install Docker Desktop / Engine and retry.",
        phase: "prepare",
      };
    }

    if (!this.project.hasDockerfile) {
      const df = ensureGeneratedDockerfile(this.project);
      if (!df && (this.plan.runtime === "docker" || this.plan.runtime === "docker-compose")) {
        return {
          success: false,
          runtime: this.plan.runtime,
          logs: "",
          error: `Unable to generate Dockerfile for project kind=${this.project.kind}`,
          phase: "prepare",
        };
      }
      if (df) this.plan.dockerfile = df;
    }

    if (this.plan.runtime === "docker-compose") {
      const composeFile = ensureGeneratedCompose(this.project, this.plan);
      if (!composeFile && !this.project.hasCompose) {
        return {
          success: false,
          runtime: "docker-compose",
          logs: "",
          error: "Unable to generate docker-compose.yml for this project",
          phase: "prepare",
        };
      }
      if (composeFile) {
        this.plan.composeFile = composeFile;
        this.project.hasCompose = true;
        this.project.composeFile = composeFile;
      }
    }

    if (this.plan.runtime === "local-process") {
      return {
        success: false,
        runtime: "local-process",
        logs: "",
        error:
          "No supported container deploy path for this project. Add a Dockerfile/compose or configure Pi Agent.",
        phase: "prepare",
      };
    }

    writeText(
      join(dirname(this.project.root), "artifacts", "plan.json"),
      JSON.stringify(this.plan, null, 2),
    );

    return {
      success: true,
      runtime: this.plan.runtime,
      logs: "Environment prepared",
      phase: "prepare",
    };
  }

  async build(): Promise<SandboxDeployResult> {
    try {
      if (this.plan.runtime === "local-process") {
        return {
          success: false,
          runtime: "local-process",
          logs: "",
          error: "local-process builds are disabled in Docker sandbox mode",
          phase: "build",
        };
      }

      if (this.plan.runtime === "docker-compose" && this.plan.composeFile) {
        return {
          success: true,
          runtime: "docker-compose",
          logs: "Compose build deferred to start phase",
          phase: "build",
        };
      }

      const tag = this.plan.imageTag;
      const dockerfile = this.plan.dockerfile || "Dockerfile";
      const { stdout, stderr } = await dockerBuild(this.project.root, tag, dockerfile);
      return {
        success: true,
        runtime: "docker",
        logs: `${stdout}\n${stderr}`.trim(),
        phase: "build",
      };
    } catch (err) {
      return {
        success: false,
        runtime: this.plan.runtime,
        logs: err instanceof Error ? err.message : String(err),
        error: err instanceof Error ? err.message : String(err),
        phase: "build",
      };
    }
  }

  async start(): Promise<SandboxDeployResult> {
    try {
      if (this.plan.runtime === "docker-compose" && this.plan.composeFile) {
        const projectName = this.composeProject();
        const { stdout, stderr } = await composeUp(
          this.project.root,
          this.plan.composeFile,
          projectName,
          this.plan.env,
        );
        const logs = await composeLogs(
          this.project.root,
          this.plan.composeFile,
          projectName,
          100,
        );
        return {
          success: true,
          runtime: "docker-compose",
          composeProject: projectName,
          logs: `${stdout}\n${stderr}\n${logs}`.trim(),
          phase: "start",
        };
      }

      const name = this.containerName();
      const containerPort = this.plan.healthPort ?? this.project.ports[0] ?? 3000;

      // Free previous DeployPilot containers still holding the preferred host port
      const freed = await freeDeployPilotPort(containerPort, name);
      let hostPort = await pickHostPort(containerPort, await listPublishedHostPorts());
      if (hostPort !== containerPort || freed.length) {
        this.plan.healthPort = hostPort;
        this.plan.healthUrl = `http://localhost:${hostPort}`;
        this.plan.env = { ...this.plan.env, PORT: String(containerPort) };
      }

      let id: string;
      try {
        id = await dockerRun({
          image: this.plan.imageTag,
          name,
          ports: [{ host: hostPort, container: containerPort }],
          env: this.plan.env,
          memoryLimit: this.config.memoryLimit,
          cpuLimit: this.config.cpuLimit,
          detach: true,
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        if (/port is already allocated|address already in use/i.test(message)) {
          await freeDeployPilotPort(hostPort, name);
          hostPort = await pickHostPort(hostPort + 1, await listPublishedHostPorts());
          this.plan.healthPort = hostPort;
          this.plan.healthUrl = `http://localhost:${hostPort}`;
          id = await dockerRun({
            image: this.plan.imageTag,
            name,
            ports: [{ host: hostPort, container: containerPort }],
            env: this.plan.env,
            memoryLimit: this.config.memoryLimit,
            cpuLimit: this.config.cpuLimit,
            detach: true,
          });
        } else {
          throw err;
        }
      }

      const logs = await dockerLogs(name, 100);
      const running = await dockerInspectRunning(name);
      if (!running) {
        return {
          success: false,
          runtime: "docker",
          containerId: id,
          logs,
          error: "Container exited immediately after start",
          phase: "start",
        };
      }
      return {
        success: true,
        runtime: "docker",
        containerId: id,
        logs:
          (freed.length ? `Freed previous containers: ${freed.join(", ")}\n` : "") +
          (hostPort !== containerPort ? `Host port remapped to ${hostPort}\n` : "") +
          logs,
        phase: "start",
      };
    } catch (err) {
      return {
        success: false,
        runtime: this.plan.runtime,
        logs: err instanceof Error ? err.message : String(err),
        error: err instanceof Error ? err.message : String(err),
        phase: "start",
      };
    }
  }

  async collectLogs(): Promise<string> {
    try {
      if (this.plan.runtime === "docker-compose" && this.plan.composeFile) {
        return await composeLogs(
          this.project.root,
          this.plan.composeFile,
          this.composeProject(),
          300,
        );
      }
      return await dockerLogs(this.containerName(), 300);
    } catch (err) {
      return err instanceof Error ? err.message : String(err);
    }
  }

  async cleanup(): Promise<void> {
    try {
      if (this.plan.runtime === "docker-compose" && this.plan.composeFile) {
        await composeDown(this.project.root, this.plan.composeFile, this.composeProject());
      } else {
        await dockerRm(this.containerName());
      }
    } catch {
      // ignore cleanup errors
    }
  }
}
