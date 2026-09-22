import { basename, join } from "node:path";
import { isDirectory, listFiles, pathExists, readJson, readText } from "./filesystem.js";
import type { ProjectInfo, ProjectKind } from "../types.js";

function detectPortsFromText(text: string): number[] {
  const ports = new Set<number>();
  const patterns = [
    /(?:PORT|port)\s*[=:]\s*["']?(\d{2,5})/g,
    /listen\((\d{2,5})/g,
    /(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d{2,5})/g,
    /EXPOSE\s+(\d{2,5})/gi,
    /(?:ports:\s*-\s*["']?)(\d{2,5}):/gi,
  ];
  for (const re of patterns) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(text))) {
      const p = Number(m[1]);
      if (p > 0 && p < 65536) ports.add(p);
    }
  }
  return [...ports];
}

function detectNode(root: string): Partial<ProjectInfo> | undefined {
  const pkgPath = join(root, "package.json");
  if (!pathExists(pkgPath)) return undefined;
  const pkg = readJson<{
    name?: string;
    scripts?: Record<string, string>;
    engines?: { node?: string };
    dependencies?: Record<string, string>;
    devDependencies?: Record<string, string>;
  }>(pkgPath);

  const deps = { ...pkg.dependencies, ...pkg.devDependencies };
  const frameworks: string[] = [];
  for (const name of [
    "next",
    "express",
    "fastify",
    "koa",
    "nestjs",
    "@nestjs/core",
    "vite",
    "react",
    "vue",
    "nuxt",
  ]) {
    if (deps[name]) frameworks.push(name.replace("@nestjs/core", "nestjs"));
  }

  let packageManager: ProjectInfo["packageManager"] = "npm";
  if (pathExists(join(root, "pnpm-lock.yaml"))) packageManager = "pnpm";
  else if (pathExists(join(root, "yarn.lock"))) packageManager = "yarn";
  else if (pathExists(join(root, "bun.lockb")) || pathExists(join(root, "bun.lock"))) {
    packageManager = "bun";
  }

  const scripts = pkg.scripts ?? {};
  const entrypoints = [
    scripts.start && "npm start",
    scripts.dev && "npm run dev",
    pathExists(join(root, "server.js")) && "server.js",
    pathExists(join(root, "index.js")) && "index.js",
  ].filter(Boolean) as string[];

  return {
    kind: "nodejs",
    name: pkg.name || basename(root),
    packageManager,
    frameworks: [...new Set(frameworks)],
    entrypoints,
    node: {
      engines: pkg.engines?.node,
      scripts,
    },
  };
}

function detectPython(root: string): Partial<ProjectInfo> | undefined {
  const requirements = join(root, "requirements.txt");
  const pyproject = join(root, "pyproject.toml");
  const setupPy = join(root, "setup.py");
  const hasPoetry = pathExists(join(root, "poetry.lock")) || (
    pathExists(pyproject) && /\[tool\.poetry\]/.test(readText(pyproject))
  );
  const hasPipenv = pathExists(join(root, "Pipfile"));
  const hasReq = pathExists(requirements);
  const hasPy = pathExists(pyproject) || pathExists(setupPy) || hasReq || hasPoetry || hasPipenv;

  if (!hasPy) {
    // Look for common app files
    const common = ["app.py", "main.py", "manage.py", "wsgi.py", "asgi.py"];
    if (!common.some((f) => pathExists(join(root, f)))) return undefined;
  }

  const frameworks: string[] = [];
  const blobs: string[] = [];
  if (hasReq) blobs.push(readText(requirements));
  if (pathExists(pyproject)) blobs.push(readText(pyproject));
  const blob = blobs.join("\n").toLowerCase();
  for (const name of ["fastapi", "flask", "django", "uvicorn", "gunicorn", "streamlit"]) {
    if (blob.includes(name) || pathExists(join(root, name === "django" ? "manage.py" : ""))) {
      if (name === "django" && !pathExists(join(root, "manage.py")) && !blob.includes("django")) {
        continue;
      }
      frameworks.push(name);
    }
  }

  const entrypoints = [
    pathExists(join(root, "manage.py")) && "python manage.py runserver",
    pathExists(join(root, "app.py")) && "python app.py",
    pathExists(join(root, "main.py")) && "python main.py",
    frameworks.includes("uvicorn") && "uvicorn main:app --host 0.0.0.0 --port 8000",
  ].filter(Boolean) as string[];

  let reqList: string[] | undefined;
  if (hasReq) {
    reqList = readText(requirements)
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter((l) => l && !l.startsWith("#"));
  }

  return {
    kind: "python",
    name: basename(root),
    frameworks: [...new Set(frameworks)],
    entrypoints,
    python: {
      requirements: reqList,
      hasPoetry,
      hasPipenv,
    },
  };
}

function detectJava(root: string): Partial<ProjectInfo> | undefined {
  const pomPath = join(root, "pom.xml");
  const gradleGroovy = join(root, "build.gradle");
  const gradleKts = join(root, "build.gradle.kts");
  const hasMaven = pathExists(pomPath);
  const hasGradle = pathExists(gradleGroovy) || pathExists(gradleKts);
  if (!hasMaven && !hasGradle) return undefined;

  const buildTool: "maven" | "gradle" = hasMaven ? "maven" : "gradle";
  let pom = "";
  if (hasMaven) {
    try {
      pom = readText(pomPath);
    } catch {
      pom = "";
    }
  }
  const gradleText = hasGradle
    ? readText(pathExists(gradleGroovy) ? gradleGroovy : gradleKts)
    : "";
  const blob = `${pom}\n${gradleText}`.toLowerCase();

  const frameworks: string[] = [];
  if (blob.includes("spring-boot")) frameworks.push("spring-boot");
  if (blob.includes("mybatis")) frameworks.push("mybatis");
  if (blob.includes("spring-cloud")) frameworks.push("spring-cloud");

  const modules: string[] = [];
  for (const m of pom.matchAll(/<module>\s*([^<]+)\s*<\/module>/gi)) {
    modules.push(m[1].trim());
  }

  // Prefer *-server / *-web / *-api / *-boot modules as runnable unit
  const serverModule =
    modules.find((m) => /server|web|api|boot|app|start/i.test(m)) ||
    modules.find((m) => pathExists(join(root, m, "src", "main"))) ||
    (pathExists(join(root, "src", "main", "java")) ? undefined : modules[0]);

  let packaging: "jar" | "war" | "pom" = "jar";
  if (/<packaging>\s*pom\s*<\/packaging>/i.test(pom)) packaging = "pom";
  else if (/<packaging>\s*war\s*<\/packaging>/i.test(pom)) packaging = "war";

  // Prefer project artifactId (skip <parent> block)
  const pomWithoutParent = pom.replace(/<parent>[\s\S]*?<\/parent>/i, "");
  const nameMatch = pomWithoutParent.match(/<artifactId>\s*([^<]+)\s*<\/artifactId>/i);
  const name = nameMatch?.[1]?.trim() || basename(root);

  // Prefer config / main class under server module
  const configRoots = serverModule
    ? [join(root, serverModule), root]
    : [root];
  const configFiles: string[] = [];
  for (const base of configRoots) {
    configFiles.push(
      ...listFiles(base, 5).filter((f) => /application.*\.(yml|yaml|properties)$/i.test(f)),
    );
  }
  let configBlob = "";
  for (const f of configFiles.slice(0, 20)) {
    try {
      configBlob += `\n${readText(f).slice(0, 8000)}`;
    } catch {
      // ignore
    }
  }

  const infraPorts = new Set([3306, 6379, 5432, 27017, 9200]);
  const rawPorts = detectPortsFromText(configBlob).filter((p) => !infraPorts.has(p));
  const serverPortMatches = [...configBlob.matchAll(/server:\s*[\r\n]+\s*port:\s*(\d+)/gi)].map(
    (m) => Number(m[1]),
  );
  const ports = [
    ...serverPortMatches,
    ...rawPorts,
    8080,
  ].filter((p, i, arr) => !infraPorts.has(p) && arr.indexOf(p) === i);

  const needsMysql = /mysql|jdbc:mysql|datasource/i.test(configBlob + blob);
  const needsRedis = /redis/i.test(configBlob + blob);

  // Find main class — prefer server module
  const javaSearchRoots = serverModule ? [join(root, serverModule), root] : [root];
  let mainClass: string | undefined;
  outer: for (const base of javaSearchRoots) {
    const javaFiles = listFiles(base, 6).filter((f) => f.endsWith("Application.java"));
    for (const f of javaFiles.slice(0, 10)) {
      try {
        const src = readText(f);
        if (/SpringBootApplication|public\s+static\s+void\s+main/.test(src)) {
          const pkg = src.match(/package\s+([\w.]+)/)?.[1];
          const cls = basename(f).replace(/\.java$/, "");
          mainClass = pkg ? `${pkg}.${cls}` : cls;
          break outer;
        }
      } catch {
        // ignore
      }
    }
  }

  const javaVersion =
    pom.match(/<java\.version>\s*([^<]+)\s*<\/java\.version>/i)?.[1]?.trim() ||
    pom.match(/maven\.compiler\.(?:source|release)>\s*([^<]+)/i)?.[1]?.trim();

  return {
    kind: "java",
    name,
    frameworks: [...new Set(frameworks)],
    entrypoints: [
      buildTool === "maven"
        ? serverModule
          ? `mvn -pl ${serverModule} -am spring-boot:run`
          : "mvn spring-boot:run"
        : "gradle bootRun",
    ],
    ports: ports.length ? ports : [8080],
    java: {
      buildTool,
      packaging,
      modules,
      serverModule,
      mainClass,
      springBoot: frameworks.includes("spring-boot") || Boolean(mainClass),
      needsMysql,
      needsRedis,
      javaVersion,
    },
    rawSignals: [
      hasMaven ? "pom.xml" : "gradle",
      serverModule ? `module:${serverModule}` : "",
      needsMysql ? "mysql" : "",
      needsRedis ? "redis" : "",
    ].filter(Boolean),
  };
}

function hasValidDockerfile(root: string): boolean {
  for (const name of ["Dockerfile", "dockerfile"]) {
    const p = join(root, name);
    if (!pathExists(p)) continue;
    try {
      const text = readText(p).trim();
      if (text.length > 10 && /FROM\s+\S+/i.test(text)) return true;
    } catch {
      // ignore
    }
  }
  return false;
}

function detectCompose(root: string): { hasCompose: boolean; composeFile?: string } {
  for (const name of [
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
  ]) {
    if (pathExists(join(root, name))) {
      return { hasCompose: true, composeFile: name };
    }
  }
  return { hasCompose: false };
}

export function inspectProject(root: string): ProjectInfo {
  if (!isDirectory(root)) {
    throw new Error(`Project root is not a directory: ${root}`);
  }

  const compose = detectCompose(root);
  const hasDockerfile = hasValidDockerfile(root);
  const node = detectNode(root);
  const python = detectPython(root);
  const java = detectJava(root);

  let kind: ProjectKind = "unknown";
  if (compose.hasCompose) kind = "docker-compose";
  else if (node) kind = "nodejs";
  else if (java) kind = "java";
  else if (python) kind = "python";
  else if (hasDockerfile) kind = "docker-compose";

  const files = listFiles(root, 2);
  const textSamples: string[] = [];
  for (const f of files.slice(0, 80)) {
    if (
      /\.(js|ts|tsx|py|yml|yaml|env|json|toml|md|xml|properties)$/i.test(f) ||
      /Dockerfile/i.test(f)
    ) {
      try {
        textSamples.push(readText(f).slice(0, 4000));
      } catch {
        // ignore binary
      }
    }
  }
  if (compose.composeFile) {
    try {
      textSamples.push(readText(join(root, compose.composeFile)));
    } catch {
      // ignore
    }
  }

  const portsFromText = detectPortsFromText(textSamples.join("\n"));
  const ports =
    (java?.ports?.length ? java.ports : undefined) ||
    (portsFromText.length ? portsFromText : undefined) ||
    (kind === "python" ? [8000] : kind === "java" ? [8080] : [3000]);

  const envFiles = [".env", ".env.example", ".env.sample"].filter((n) =>
    pathExists(join(root, n)),
  );

  const base: ProjectInfo = {
    name: java?.name || node?.name || basename(root),
    kind,
    root,
    frameworks: [],
    entrypoints: [],
    hasDockerfile,
    hasCompose: compose.hasCompose,
    composeFile: compose.composeFile,
    ports,
    envFiles,
    rawSignals: [
      hasDockerfile ? "dockerfile" : "",
      compose.hasCompose ? `compose:${compose.composeFile}` : "",
      node ? "package.json" : "",
      python ? "python" : "",
      java ? "java" : "",
    ].filter(Boolean),
  };

  if (kind === "docker-compose" || compose.hasCompose) {
    return {
      ...base,
      kind: "docker-compose",
      frameworks: [
        ...(node?.frameworks ?? []),
        ...(python?.frameworks ?? []),
        ...(java?.frameworks ?? []),
      ],
      entrypoints: ["docker compose up"],
      packageManager: node?.packageManager,
      node: node?.node,
      python: python?.python,
      java: java?.java,
    };
  }

  if (node) {
    return {
      ...base,
      ...node,
      kind: "nodejs",
      hasDockerfile,
      hasCompose: compose.hasCompose,
      composeFile: compose.composeFile,
      ports: portsFromText.length ? portsFromText : [3000],
      envFiles,
      rawSignals: base.rawSignals,
    };
  }

  if (java) {
    return {
      ...base,
      ...java,
      kind: "java",
      hasDockerfile,
      hasCompose: compose.hasCompose,
      composeFile: compose.composeFile,
      ports: java.ports?.length ? java.ports : [8080],
      envFiles,
      rawSignals: [...base.rawSignals, ...(java.rawSignals ?? [])],
    };
  }

  if (python) {
    return {
      ...base,
      ...python,
      kind: "python",
      hasDockerfile,
      hasCompose: compose.hasCompose,
      ports: portsFromText.length ? portsFromText : [8000],
      envFiles,
      rawSignals: base.rawSignals,
    };
  }

  return base;
}

export function buildHeuristicPlan(
  project: ProjectInfo,
  imageTag: string,
): import("../types.js").DeployPlan {
  const port =
    project.ports[0] ??
    (project.kind === "python" ? 8000 : project.kind === "java" ? 8080 : 3000);

  if (project.hasCompose && project.composeFile) {
    return {
      summary: `Deploy via existing ${project.composeFile}`,
      runtime: "docker-compose",
      imageTag,
      composeFile: project.composeFile,
      buildCommands: [`docker compose -f ${project.composeFile} build`],
      startCommands: [`docker compose -f ${project.composeFile} up -d`],
      healthPort: port,
      healthUrl: `http://localhost:${port}`,
      env: { PORT: String(port) },
      notes: ["Using project-provided compose file"],
      generatedBy: "heuristic",
    };
  }

  if (project.kind === "java") {
    const needsDb = Boolean(project.java?.needsMysql || project.java?.needsRedis);
    return {
      summary: needsDb
        ? `Maven/Spring Boot app with generated docker-compose (MySQL/Redis + app)`
        : `Containerize Java/Maven app and expose port ${port}`,
      runtime: needsDb ? "docker-compose" : "docker",
      imageTag,
      dockerfile: "Dockerfile",
      composeFile: needsDb ? "docker-compose.yml" : undefined,
      buildCommands: needsDb
        ? ["docker compose -f docker-compose.yml build"]
        : [`docker build -t ${imageTag} .`],
      startCommands: needsDb
        ? ["docker compose -f docker-compose.yml up -d"]
        : [
            `docker run -d --name ${imageTag.replace(/[:/]/g, "-")} -p ${port}:${port} ${imageTag}`,
          ],
      healthPort: port,
      healthUrl: `http://localhost:${port}`,
      env: {
        SERVER_PORT: String(port),
        SKY_DATASOURCE_HOST: "mysql",
        SKY_DATASOURCE_PORT: "3306",
        SKY_DATASOURCE_DATABASE: "sky_take_out",
        SKY_DATASOURCE_USERNAME: "root",
        SKY_DATASOURCE_PASSWORD: "123456",
        SKY_REDIS_HOST: "redis",
        SKY_REDIS_PORT: "6379",
        SKY_REDIS_PASSWORD: "",
        SKY_REDIS_DATABASE: "0",
      },
      notes: [
        project.java?.serverModule
          ? `Runnable module: ${project.java.serverModule}`
          : "Single-module Java build",
        needsDb ? "Infra services will be provisioned via compose" : "Standalone jar container",
      ],
      generatedBy: "heuristic",
    };
  }

  if (project.kind === "nodejs") {
    const pm = project.packageManager ?? "npm";
    const startScript = project.node?.scripts?.start
      ? `${pm === "npm" ? "npm start" : `${pm} start`}`
      : project.node?.scripts?.dev
        ? `${pm === "npm" ? "npm run dev" : `${pm} run dev`}`
        : "node index.js";

    return {
      summary: `Containerize Node.js app (${pm}) and expose port ${port}`,
      runtime: "docker",
      imageTag,
      dockerfile: "Dockerfile",
      buildCommands: ["docker build -t " + imageTag + " ."],
      startCommands: [
        `docker run -d --name ${imageTag.replace(/[:/]/g, "-")} -p ${port}:${port} -e PORT=${port} ${imageTag}`,
      ],
      healthPort: port,
      healthUrl: `http://localhost:${port}`,
      env: { PORT: String(port), NODE_ENV: "production" },
      notes: [`Start command inside image should run: ${startScript}`],
      generatedBy: "heuristic",
    };
  }

  if (project.kind === "python") {
    const cmd =
      project.entrypoints.find((e) => e.includes("uvicorn")) ||
      project.entrypoints[0] ||
      "python app.py";
    return {
      summary: `Containerize Python app and expose port ${port}`,
      runtime: "docker",
      imageTag,
      dockerfile: "Dockerfile",
      buildCommands: ["docker build -t " + imageTag + " ."],
      startCommands: [
        `docker run -d --name ${imageTag.replace(/[:/]/g, "-")} -p ${port}:${port} -e PORT=${port} ${imageTag}`,
      ],
      healthPort: port,
      healthUrl: `http://localhost:${port}`,
      env: { PORT: String(port) },
      notes: [`Suggested CMD: ${cmd}`],
      generatedBy: "heuristic",
    };
  }

  return {
    summary: "Unknown project type; refusing to invent a broken Docker build",
    runtime: project.hasDockerfile ? "docker" : "local-process",
    imageTag,
    dockerfile: project.hasDockerfile ? "Dockerfile" : undefined,
    buildCommands: project.hasDockerfile ? [`docker build -t ${imageTag} .`] : [],
    startCommands: project.hasDockerfile
      ? [`docker run -d --name ${imageTag.replace(/[:/]/g, "-")} -p ${port}:${port} ${imageTag}`]
      : [],
    healthPort: port,
    healthUrl: `http://localhost:${port}`,
    env: {},
    notes: [
      "Unsupported project type for heuristic deploy. Configure a Pi model or add Dockerfile/compose.",
    ],
    generatedBy: "heuristic",
  };
}
