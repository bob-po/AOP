export type DeployMode = "docker" | "local";
export type DeployTarget = "local" | `ssh://${string}`;

export type TaskStatus =
  | "pending"
  | "cloning"
  | "analyzing"
  | "planning"
  | "preparing"
  | "building"
  | "starting"
  | "health_check"
  | "repairing"
  | "succeeded"
  | "failed"
  | "interrupted"
  | "cleaned";

export type StepId =
  | "clone"
  | "analyze"
  | "plan"
  | "prepare"
  | "build"
  | "start"
  | "health";

export type StepStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface DeployStep {
  id: StepId;
  label: string;
  status: StepStatus;
  startedAt?: string;
  finishedAt?: string;
  error?: string;
}

export type ProjectKind = "nodejs" | "python" | "java" | "docker-compose" | "unknown";

export interface ProjectInfo {
  name: string;
  kind: ProjectKind;
  root: string;
  packageManager?: "npm" | "pnpm" | "yarn" | "bun";
  frameworks: string[];
  entrypoints: string[];
  hasDockerfile: boolean;
  hasCompose: boolean;
  composeFile?: string;
  python?: {
    versionHint?: string;
    requirements?: string[];
    hasPoetry: boolean;
    hasPipenv: boolean;
  };
  node?: {
    engines?: string;
    scripts: Record<string, string>;
  };
  java?: {
    buildTool: "maven" | "gradle";
    packaging: "jar" | "war" | "pom";
    modules: string[];
    serverModule?: string;
    mainClass?: string;
    springBoot: boolean;
    needsMysql: boolean;
    needsRedis: boolean;
    javaVersion?: string;
  };
  ports: number[];
  envFiles: string[];
  rawSignals: string[];
}

export interface DeployPlan {
  summary: string;
  runtime: "docker" | "docker-compose" | "local-process";
  imageTag: string;
  composeFile?: string;
  dockerfile?: string;
  buildCommands: string[];
  startCommands: string[];
  healthUrl?: string;
  healthPort?: number;
  env: Record<string, string>;
  notes: string[];
  generatedBy: "agent" | "heuristic";
}

export interface RepairRecord {
  attempt: number;
  at: string;
  step: StepId;
  errorSummary: string;
  action: string;
  success: boolean;
}

export interface DeploymentResult {
  success: boolean;
  status: "healthy" | "unhealthy" | "unknown" | "failed";
  url?: string;
  runtime?: string;
  containerId?: string;
  composeProject?: string;
  logsDir: string;
  repairs: RepairRecord[];
  error?: string;
}

export interface DeployInput {
  source: string;
  mode?: DeployMode;
  target?: string;
  maxRepairAttempts?: number;
  memoryLimit?: string;
  cpuLimit?: string;
  model?: string;
  taskId?: string;
  resume?: boolean;
}

export interface TaskRecord {
  id: string;
  createdAt: string;
  updatedAt: string;
  status: TaskStatus;
  input: DeployInput;
  workspaceDir: string;
  sourceDir: string;
  logsDir: string;
  steps: DeployStep[];
  project?: ProjectInfo;
  plan?: DeployPlan;
  result?: DeploymentResult;
  repairs: RepairRecord[];
  events: Array<{ at: string; message: string; level: "info" | "warn" | "error" | "agent" }>;
  agentSessionFile?: string;
}

export interface AppConfig {
  homeDir: string;
  tasksDir: string;
  workspacesDir: string;
  configPath: string;
  model?: string;
  mode: DeployMode;
  maxRepairAttempts: number;
  memoryLimit: string;
  cpuLimit: string;
  anthropicApiKey?: string;
  openaiApiKey?: string;
  googleApiKey?: string;
}

export const DEPLOY_STEPS: Array<{ id: StepId; label: string }> = [
  { id: "clone", label: "Cloning repository" },
  { id: "analyze", label: "Analyzing project" },
  { id: "plan", label: "Generating deployment plan" },
  { id: "prepare", label: "Preparing environment" },
  { id: "build", label: "Building project" },
  { id: "start", label: "Starting services" },
  { id: "health", label: "Health verification" },
];
