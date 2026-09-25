# Agent 沙箱策略（Phase 22 + Phase 27）

控制面在发起 A2A 调用前施加的执行护栏，配合 Compose 对 Agent 容器的 **seccomp / capabilities / 资源限额**。

## 分层

| 层 | 内容 |
|----|------|
| 策略层（Orchestrator） | endpoint/skill 白名单、输入输出截断、高危 skill 宿主校验 |
| 容器层（Compose） | `no-new-privileges`、`cap_drop: ALL`、自定义 seccomp、只读根 FS（Code） |
| 运行时（Harness） | profile 级 sandbox；code skill 走 hardened/code seccomp；可选 egress allowlist |

## 默认行为

| 开关 | 默认 | 说明 |
|------|------|------|
| `AGENT_SANDBOX` | `1` | 总开关 |
| `AGENT_SANDBOX_STRICT` | `0` | 额外拦截 metadata / 非白名单私网 IP |
| `AGENT_ALLOW_HIGH_RISK` | `1`（Compose） | 允许 `code-execution` / `browser-automation` |
| `AOP_RUNTIME` | （空）/ compose 为 `docker` | `docker` 时保留服务 DNS |
| `AOP_SECCOMP_DIR` | `deployments/seccomp` | 策略校验用 profile 目录 |
| `BROWSER_EGRESS_ALLOWLIST` | 空 = 任意 http(s) | 逗号分隔 host / `*.suffix` |

## 策略项

| 环境变量 | 作用 |
|----------|------|
| `AGENT_ENDPOINT_ALLOWLIST` | 允许的 hostname（逗号分隔）；空则用内置 Agent 列表 + localhost |
| `AGENT_SKILL_ALLOWLIST` | 仅允许这些 skill（空 = 不限制） |
| `AGENT_SKILL_DENYLIST` | 拒绝的 skill |
| `AGENT_MAX_INPUT_CHARS` | 输入截断（默认 50000） |
| `AGENT_MAX_OUTPUT_CHARS` | 输出截断（默认 200000） |
| `AGENT_SKILL_TIMEOUTS` | 如 `code-execution:30,browser-automation:60` |
| `A2A_TIMEOUT` | 默认超时秒数 |

高危 skill 必须打到专用 / 受信主机（specialty agent 已下线，默认对 harness 虚拟机身份 + localhost）：

| Skill | 允许 host |
|-------|-----------|
| `code-execution` | `*-coder` harness（如 `claude-coder`）/ localhost |

违规时 Worker 将节点记为失败：`sandbox: …`。

## Seccomp 配置文件

路径：`deployments/seccomp/`

| 文件 | 用途 |
|------|------|
| `agent-hardened.json` | 通用 Agent：default ERRNO + Python/uvicorn 白名单 |
| `code-agent.json` | Code：更紧白名单 + 显式拒绝 mount/bpf/ptrace/module |

Compose（`docker-compose.single.yml`）为 harness 虚拟 agent 服务挂载对应 `security_opt`；coder profile 另可挂 `code-agent.json`。

## Compose 资源限额

每个 harness 虚拟 agent 服务：

- CPU limit `1.0` / reservation `0.1`
- Memory limit `512M` / reservation `64M`

## 冒烟

```bash
cd apps/orchestrator
python scripts/phase22_sandbox.py
python scripts/phase27_seccomp.py
```

## 后续可选

- 租户级沙箱配额与出站 iptables 网关
- Code Agent 可选 microVM（Firecracker）隔离

## Chromium / Browser Agent（已下线）

`browser-agent`、`docker-compose.browser-chromium.yml` 与 `browser-agent.json` seccomp profile 均已移除。
