# 《A2A Agent 调度平台 v1.0 技术方案》

| 字段 | 内容 |
|------|------|
| 版本 | v1.0 |
| 定位 | 基于 A2A 协议的多 Agent 注册、发现、调度、编排与执行平台 |
| 目标 | 构建可扩展的 **Agent Control Plane** |
| 状态 | **Phase 1–12 已落地**（核心闭环 + Marketplace / HITL / Memory / Metrics） |
| 关联文档 | [数据库设计](./database.md) · [API 设计](./api.md) · [Redis 设计](./redis.md) · [MVP 开发计划](./mvp-plan.md) · [架构索引](./architecture.md) |

---

## 1. 项目概述

### 1.1 项目定位

本项目旨在构建面向多 Agent 协作场景的统一调度平台。

平台**不直接承担所有业务任务**，而是作为：

> **Agent 注册中心 + 能力发现中心 + 调度中心 + 执行控制中心 + 运行监控中心**

用户只需提出目标，例如：

> 「帮我分析这个公司的资料，并生成一份 PPT。」

平台自动完成：

```
用户请求 → 任务理解 → 任务规划 → 任务拆分 → Agent 能力发现
        → Agent 路由 → A2A 调用 → 多 Agent 协作 → 结果聚合 → 最终结果
```

### 1.2 核心分工

| 层级 | 解决的问题 |
|------|------------|
| **A2A 协议** | Agent ↔ Agent **怎么说话** |
| **本平台** | Agent ↔ Agent **为什么通信**；任务如何组织、调度、失败恢复、结果合并 |

调度 Agent **不一定亲自完成任务**，而是负责：找谁做、怎么做、什么时候做、结果怎么合并。

### 1.3 与 Google A2A 的关系

A2A 是 Agent 间通信协议/标准，**不等于必须使用 Google API**。

平台可以：

- 对接自研 Python/Go Agent（符合 A2A）
- 对接第三方 A2A Agent
- 将现有能力（企业 RAG / ComfyUI / AIVE / Lumin）逐步 Agent 化

```
Orchestrator ──A2A──► RAG Agent / Image Agent / Coding Agent / Robot Agent
```

---

## 2. 核心设计理念

围绕 9 个问题拆模块：

| 问题 | 对应模块 |
|------|----------|
| 有哪些 Agent？ | Agent Registry |
| Agent 能做什么？ | Agent Skill / Agent Card |
| 任务应该怎么拆？ | Planner |
| 每个任务交给谁？ | Router |
| Agent 怎么通信？ | A2A |
| 多个任务怎么执行？ | Scheduler + Task DAG |
| 执行过程怎么查看？ | Task Trace |
| Agent 出问题怎么办？ | Retry / Failover |
| Agent 是否可用？ | Health Monitor |

**投入优先级（v1.0 → 已推进至 Phase 12）：**

```
★★★★★  Agent Registry / Task DAG / Planner / Router / A2A Executor     ✅
★★★★☆  Scheduler / Task Trace / Artifact                               ✅
★★★☆☆  Marketplace / Workflow / Health Monitor                         ✅
★★★☆☆  Evaluation / Memory / HITL / 智能路由 / Metrics                 ✅
★★☆☆☆  Billing / 跨任务长期 Memory / 完整 RBAC UI                      未做
```

---

## 3. 总体架构

### 3.1 架构总览

```
                              ┌──────────────────────┐
                              │        User          │
                              └──────────┬───────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │     Web Console      │
                              │       Next.js        │
                              └──────────┬───────────┘
                                         │
                                         ▼
┌──────────────────────────────────────────────────────────────────┐
│                         API Gateway (Go / Chi)                   │
│ Auth │ Tenant │ API Key │ Rate Limit │ Task API │ Agent API      │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                       Orchestrator (Python)                      │
│ ┌──────────┐ ┌──────────┐ ┌────────────┐ ┌──────────────────┐   │
│ │ Planner  │ │ Router   │ │ Scheduler  │ │ Task Aggregator  │   │
│ └──────────┘ └──────────┘ └────────────┘ └──────────────────┘   │
└──────────────┬──────────────────────┬────────────────────────────┘
               │                      │
               ▼                      ▼
       ┌──────────────┐       ┌────────────────┐
       │ Agent        │       │ Task State     │
       │ Registry     │       │ Redis Streams  │
       └──────┬───────┘       └────────────────┘
              │
              ▼
       ┌───────────────────────────────────────────┐
       │              A2A Communication Layer      │
       └──────┬───────────────┬───────────────┬────┘
              │               │               │
              ▼               ▼               ▼
       ┌───────────┐   ┌────────────┐   ┌────────────┐
       │ RAG Agent │   │ Image      │   │ Video      │
       │           │   │ Agent      │   │ Agent      │
       └─────┬─────┘   └─────┬──────┘   └─────┬──────┘
             ▼               ▼               ▼
         Vector DB        ComfyUI          AIVE
```

### 3.2 系统分层（8 层）

| Layer | 名称 | 职责 |
|-------|------|------|
| 8 | Console | Chat / Agent / Task / Workflow / Monitor |
| 7 | Gateway | Auth / API Key / Rate Limit / Tenant |
| 6 | Orchestrator | Intent / Plan / Discover / Select / Schedule / Aggregate |
| 5 | Agent Registry | 能力地图、版本、Endpoint、健康状态 |
| 4 | A2A Communication | Task / Message / Artifact 协议 |
| 3 | Agent Runtime | Docker / Sandbox / GPU |
| 2 | Infrastructure | PostgreSQL / Redis / MinIO |
| 1 | External Services | LLM / ComfyUI / AIVE / Vector DB / Web Search |

### 3.3 调度内核拆分（非单一超级 Agent）

```
                 Orchestrator
                      │
       ┌──────────────┼──────────────┐
       ▼              ▼              ▼
 Planner Agent   Router Agent   Executor Agent
       │              │              │
   任务分解 → DAG   Agent 选择    发送 A2A Task
```

| 组件 | 职责 |
|------|------|
| **Planner** | 用户目标 → 任务拆解 → Task DAG |
| **Router** | Skill 匹配 + 状态/延迟/成本/成功率/优先级 → 选定 Agent |
| **Executor** | 创建 A2A Task → 等待/流式接收 Artifact → 更新状态 → 触发下游 |
| **Scheduler** | 依赖检查 → 就绪节点入队 → 并发控制 |
| **Aggregator** | 合并多节点 Artifact → 最终用户结果 |

### 3.4 与现有项目的关系

```
                 A2A Platform          ← Agent Infrastructure
                      │
                 Agent Layer
                      │
                 Lumin Layer           ← AI Provider Infrastructure
                      │
              Model / API Providers    ← OpenAI / DashScope / Kling / Jimeng ...
```

| 现有能力 | 演化目标 |
|----------|----------|
| 企业 RAG | RAG Agent |
| ComfyUI | Image Agent |
| AIVE | Video Agent |
| Lumin Gateway + PG + Redis + MinIO + Adapter | 平台基础设施复用 |

---

## 4. Console 前端（v1.0）

**技术：** Next.js · React · TypeScript · TailwindCSS · shadcn/ui

**交互范式：** 中央对话框 + 任务可视化（类似「AI 操作系统」）

### 4.1 首页

```
┌──────────────────────────────────────────────────────────┐
│ A2A OS                                      Agents  Tasks │
│                                                          │
│                  What can I do for you?                  │
│                                                          │
│       ┌────────────────────────────────────────┐         │
│       │ 帮我分析这个公司的业务并生成PPT        │         │
│       │                                  ➤     │         │
│       └────────────────────────────────────────┘         │
│                                                          │
│   Research     RAG     Image     Video     Code          │
└──────────────────────────────────────────────────────────┘
```

### 4.2 Task 工作台

提交后进入 Task 页：左侧 DAG 可视化，右侧 Task Details + 实时 Trace。

```
Task #TASK-001
Status: Running | Agents: 5 | Completed: 3 | Running: 1 | Failed: 0
Latency: 24.3s | Tokens: 12.4K | Cost: $0.18
```

### 4.3 Task Trace（强制交付）

```
10:21:03  Task Created
10:21:04  Planner → 分解为 4 个子任务
10:21:05  Search Agent Running
10:21:05  RAG Agent Running
10:21:08  Search Agent Completed
10:21:10  RAG Agent Completed
10:21:11  Analysis Agent Running
10:21:24  Report Agent Completed
10:21:26  Task Completed
```

定位：**Agent Observability + Orchestration Platform**

---

## 5. Agent Registry（最核心基础设施）

### 5.1 职责

- 注册 / 查询 / 更新 / 删除
- Agent Card、Skill、Endpoint、Version
- Health、Metrics、生命周期

### 5.2 Agent 生命周期

```
Created → Registered → Verified → Online → Running → Offline → Disabled
```

### 5.3 Agent Card（身份证）

```json
{
  "name": "Enterprise RAG Agent",
  "description": "企业知识库检索和问答",
  "url": "https://rag.example.com/a2a",
  "version": "1.0.0",
  "protocol": "A2A",
  "capabilities": {
    "streaming": true
  },
  "skills": [
    {
      "id": "knowledge-search",
      "name": "Knowledge Search",
      "description": "搜索企业知识库"
    },
    {
      "id": "qa",
      "name": "Question Answering",
      "description": "基于企业知识库回答问题"
    }
  ],
  "input_modes": ["text"],
  "output_modes": ["text", "json"]
}
```

### 5.4 Skill 粒度

不要只用 `agent.type = image`，应细化：

```
Image Agent
├── text-to-image
├── image-edit
├── inpainting
├── outpainting
└── upscale
```

### 5.5 注册流程

```
POST /v1/agents/register { "endpoint": "https://rag.example.com/a2a" }
        │
        ▼
获取 Agent Card → 验证 → 解析 Skills → 写入 Registry → Health Check → Online
```

### 5.6 监控指标

| 指标 | 说明 |
|------|------|
| Health | ONLINE / DEGRADED / OFFLINE / DISABLED |
| Latency | 平均 / P95 |
| Success Rate | 成功率 |
| Error Rate | 失败率 |
| Concurrency | 当前/上限 |
| Cost | 每任务成本 |
| Last Active | 最近活跃时间 |

健康检查建议间隔：**30s**

### 5.7 Agent Marketplace（已落地 · Phase 7b）

```
Agent Marketplace
 ├── 官方 / 本地 curated packages
 └── Install → Registry register(endpoint)
```

能力：目录搜索 · 安装（拉 Card）· 与 Agents 页「市场」Tab 联动。完整第三方商店 / 计费未做。

---

## 6. Orchestrator 核心

### 6.1 Planner → Task DAG

**输入：** 自然语言目标  
**输出：** 可执行的有向无环图（DAG），节点绑定 **skill**（而非写死 agent_id）

用户：

> 分析公司 A 过去三年的业务情况，并生成一份 PPT。

Planner 输出示例：

```json
{
  "task_id": "task_001",
  "nodes": [
    { "id": "search", "skill": "web-search" },
    { "id": "finance", "skill": "financial-analysis" },
    {
      "id": "analysis",
      "skill": "business-analysis",
      "depends_on": ["search", "finance"]
    },
    {
      "id": "ppt",
      "skill": "presentation-generation",
      "depends_on": ["analysis"]
    }
  ]
}
```

执行形态：

```
             ┌─ Search ──┐
User → Plan ─┤            ├→ Analysis → Report
             └─ Finance ──┘
```

**必须用 DAG，而不是仅线性链**，以支持并行、依赖、条件分支（条件执行可在后续版本增强）。

### 6.2 Router

| 阶段 | 策略 | 状态 |
|------|------|------|
| v1.0 | Skill Match + Online | ✅ |
| v1.1 | + Priority + Availability | ✅ |
| v2.0 | + Latency + Success Rate（`agent_runs` 窗口）可配置 Score | ✅ Phase 11 |

内部 Score 通过 `GET /v1/router/preview` 供调试；不对用户展示为「Agent 排行榜」。

Failover 仅在候选 Agent **具备兼容 Skill** 时允许切换（`exclude_agent_ids`）。

环境变量：`ROUTER_SMART`（默认 true）、`ROUTER_METRICS_HOURS`（默认 24）。

### 6.3 Scheduler

```
Task Queue → Dependency Check → Runnable Nodes
         → Agent Selection (Router) → Execution
         → Result → Unlock Next Nodes
```

### 6.4 Executor（A2A）

```
Load Agent Card → Auth → Create A2A Task → Send
              → Stream/Poll → Receive Artifact → Update Task State
```

平台内部统一走 **A2A Client**，禁止把具体 Agent 实现写死进 Orchestrator。

### 6.5 Task / Node 状态机

**Task：**

```
CREATED → PLANNING → READY → RUNNING
                          ├→ WAITING_FOR_USER → (approve) → RUNNING / COMPLETED
                          │                   └→ (reject)  → FAILED
                          ├→ COMPLETED
                          ├→ FAILED
                          └→ CANCELLED
```

**Node：**

```
PENDING | READY | RUNNING | SUCCESS | WAITING_FOR_USER
        | FAILED | RETRYING | SKIPPED | CANCELLED
```

HITL：`plan_json.nodes[].requires_approval` 或 skill ∈ `HITL_SKILLS` 时，节点成功后进入 `waiting_for_user`，不立即解锁下游。

### 6.6 Retry 策略（默认）

```
max_retry = 3
backoff   = 1s → 3s → 10s
NODE_STALE_SECONDS = 900   # 长任务 running 超时回收
```

失败后可按 Router 策略切换到同 Skill 的其他 Agent（`exclude_agent_ids`）。

---

## 7. A2A 与 Agent Runtime

### 7.1 A2A 层职责

统一抽象：

```
A2A Client
 ├── Agent Card
 ├── Task
 ├── Message
 └── Artifact
```

Agent 对外暴露标准接口（按 A2A 规范实现），例如：

```
POST /a2a
```

### 7.2 Agent 内部可任意实现

```
A2A Agent
 ├── LLM
 ├── Tool
 ├── Database
 ├── ComfyUI
 ├── Python
 └── Docker
```

### 7.3 推荐第一批 Agent

| Agent | 后端能力 | MVP |
|-------|----------|-----|
| Search Agent | Web Search | ✓ |
| RAG Agent | Vector DB / 企业知识库 | ✓ |
| Report Agent | Markdown / PDF / PPT | ✓ |
| Image Agent | ComfyUI | Phase 2 |
| Video Agent | AIVE | Phase 2 |
| Code Agent | Sandbox + Git | Phase 2 |

后续：SQL / Data Analysis / OCR / Translation / Robot / Vision

### 7.4 Docker 化 Agent（推荐形态）

```
agents/
├── rag-agent/
│   ├── Dockerfile
│   ├── agent.py
│   └── agent-card.json
├── search-agent/
├── image-agent/
└── report-agent/
```

```
docker run → Agent 启动 → Register → Health Check → A2A Endpoint Online
```

### 7.5 隔离与安全（从 v1 起考虑）

尤其是 Code / Browser / RPA Agent：

- Docker + Sandbox + Resource Limit（CPU / Memory / GPU / Network / Storage）
- API Key → Tenant → Permission → Agent → Task
- 权限点：`agent.execute` / `agent.read` / `agent.register` / `agent.admin`

---

## 8. Artifact 系统

Agent 不应只返回纯文本，应统一 Artifact：

```
Artifact
├── Text
├── JSON
├── Image
├── Video
├── Audio
├── File
└── Structured Data
```

示例：

```json
{
  "type": "image",
  "uri": "s3://bucket/artifacts/task-001/image/001.png",
  "mime_type": "image/png"
}
```

**存储（复用 MinIO）：**

```
artifacts/
task-inputs/
task-outputs/
agent-files/

task-001/
├── input.pdf
├── search.json
├── analysis.json
├── report.pptx
└── final.pdf
```

Artifact 在 DAG 节点间传递，支撑多模态链路（如 Image → Video）。

---

## 9. Workflow（稳定 DAG 模板化）

| 概念 | 含义 |
|------|------|
| Agent | 单一能力 |
| Workflow | 能力组合（可复用 DAG 模板） |
| Task | 一次具体执行 |

示例「企业研究 Workflow」：

```
Search → RAG → Analysis → Report → PPT
```

用户可直接「执行 Workflow」，无需每次重新 Planner。

---

## 10. 技术栈

| 模块 | 技术 |
|------|------|
| Frontend | Next.js + Tailwind + shadcn/ui |
| Gateway | Go + Chi |
| Orchestrator | Python |
| Agent Runtime | Python（FastAPI 等） |
| A2A Client | Python / Go |
| DB | PostgreSQL |
| Queue / Events | Redis Streams |
| Object Storage | MinIO |
| Container | Docker |
| Reverse Proxy | Caddy / Nginx |
| Monitoring | Prometheus + Grafana |
| Logging | Loki |
| Tracing | OpenTelemetry |

**分工原则：**

- **Go**：高并发 API、Auth、Tenant、Rate Limit
- **Python**：Planner、Router、Scheduler、Executor、AI/Agent 生态

---

## 11. 仓库与目录结构

```
a2a-platform/
│
├── apps/
│   ├── gateway/                 # Go
│   │   ├── cmd/
│   │   ├── internal/
│   │   └── go.mod
│   ├── orchestrator/            # Python 调度核心
│   │   ├── planner/
│   │   ├── router/
│   │   ├── scheduler/
│   │   ├── executor/
│   │   ├── aggregator/
│   │   └── main.py
│   └── web/                     # Next.js
│       ├── app/
│       ├── components/
│       └── lib/
│
├── agents/
│   ├── rag-agent/
│   ├── search-agent/
│   ├── image-agent/
│   ├── video-agent/
│   └── report-agent/
│
├── packages/
│   ├── a2a-sdk/
│   ├── schemas/
│   └── common/
│
├── infrastructure/
│   ├── postgres/
│   ├── redis/
│   └── minio/
│
├── deployments/
│   ├── docker-compose.yml
│   └── k8s/
│
└── docs/
    ├── A2A-Agent-调度平台-v1.0-技术方案.md   # 本文档
    ├── architecture.md
    ├── database.md
    ├── redis.md
    ├── api.md
    ├── agent.md
    ├── a2a.md
    ├── task.md
    ├── workflow.md
    └── mvp-plan.md
```

---

## 12. MVP 范围与验收

### 12.1 v1.0 必须模块（7 个）

1. Agent Registry  
2. Agent Card  
3. Agent Discovery  
4. Planner  
5. Router  
6. A2A Executor  
7. Task Trace  

### 12.2 第一条完整链路

```
用户 → Chat → Orchestrator → Planner → Discovery → Router
    → A2A → RAG Agent → A2A → Report Agent → Aggregator → 用户
```

MVP 第一批 Agent：**Search / RAG / Report**

### 12.3 推荐首个 Demo（不要只做「你好 → RAG」）

```
帮我研究一个 AI 产品：
Search → RAG → Image（可选）→ Analysis → Report
```

证明：Registry + Planner + Router + DAG 并行 + A2A + Artifact + Trace

### 12.4 v1.0 验收清单（10 项全部通过）

- [x] Agent 可以注册  
- [x] Agent Card 可以读取  
- [x] Agent Skill 可以发现  
- [x] 用户可以创建 Task  
- [x] Planner 可以生成 DAG  
- [x] Router 可以选择 Agent  
- [x] Executor 可以进行 A2A 调用  
- [x] 多 Agent 可以并行执行  
- [x] Artifact 可以传递  
- [x] 前端可以实时看到 Task Trace  

**扩展（第三 / 四阶段）：** Workflow · Marketplace · API Key · Evaluation · 智能路由 · HITL · Memory · Metrics · 长任务回收 — 均已落地。详见 [mvp-plan.md](./mvp-plan.md)。

---

## 13. 分期路线图

| Phase | 内容 | 状态 |
|-------|------|------|
| **1** | A2A Agent + A2A Client + 单 Agent 调用 | ✅ |
| **2** | Agent Registry + Discovery + Router | ✅ |
| **3** | Planner + Task DAG + Scheduler | ✅ |
| **4** | Redis Streams + 异步执行 + Retry / Failover | ✅ |
| **5** | Artifact + MinIO + 多模态 Agent | ✅ |
| **6** | Next.js Console + Task Graph + 实时 Trace | ✅ |
| **7** | Workflow + Marketplace + Health | ✅ |
| **8** | 多租户 API Key 鉴权 | ✅ |
| **9** | 六大 Console 页面 | ✅ |
| **10** | Task Evaluation | ✅ |
| **11** | 智能路由 + HITL | ✅ |
| **12** | Memory + Observability + 长任务回收 | ✅ |

**第二阶段增强：** DAG 并行、Retry、Failover、Artifact、Task Trace — ✅  
**第三阶段：** Marketplace、Workflow、多租户 API Key、Evaluation — ✅（完整 RBAC UI / Billing 仍弱化）  
**第四阶段：** 智能路由、Memory、HITL、长任务、Observability — ✅（跨任务向量 Memory / Grafana 栈可选后续）

---

## 14. Human-in-the-loop（已落地 · Phase 11）

```
Agent 生成报告（skill ∈ HITL_SKILLS）
  → node/task status = waiting_for_user
  → 用户 Approve → 解锁下游 / 完成
  → 用户 Reject  → task failed + Evaluation
```

环境变量：`HITL_SKILLS`（默认 `report-generation`；设为 `off` 关闭）。  
API：`POST /v1/tasks/{id}/approve|reject`。Console Tasks 页提供批准 / 驳回。

---

## 15. 多租户模型（企业化 · 部分落地）

```
Tenant
 ├── Users          （表预留）
 ├── API Keys       ✅ Phase 8
 ├── Agents         ✅ tenant_id
 ├── Tasks          ✅ tenant_id
 ├── Workflows      ✅
 └── Billing        （未做）
```

数据按 Tenant 隔离字段已具备；v1 默认单租户 + 可选强制 API Key。

---

## 16. 最终产品形态

```
┌─────────────────────────────────────────────────────────────┐
│                         A2A OS                              │
├───────────────┬─────────────────────────────────────────────┤
│ Agent         │                Workspace                    │
│ Registry      │  Task Visualization (DAG) + HITL            │
│ ○ Search      │  Search ──┐                                 │
│ ○ RAG         │           ├── Analysis ── Report            │
│ ○ Image       │  RAG ─────┘                                 │
│ ○ Video       │  Memory · Evaluation · Metrics              │
│ ○ Analysis    │                                             │
├───────────────┴─────────────────────────────────────────────┤
│ Task │ Agents │ Workflows │ Artifacts │ Settings            │
└─────────────────────────────────────────────────────────────┘
```

> 本平台不是「A2A Demo」，而是支持 **注册、发现、调度、执行、监控与编排** 的 Agent Control Plane。

---

## 17. 文档索引

| 文档 | 内容 |
|------|------|
| [architecture.md](./architecture.md) | 落地架构索引与关键路径 |
| [database.md](./database.md) | PostgreSQL 表结构与 ER |
| [redis.md](./redis.md) | Redis Streams / 队列 / 锁 |
| [api.md](./api.md) | Gateway REST API（至 Phase 12） |
| [mvp-plan.md](./mvp-plan.md) | Phase 1–12 任务拆分与验收 |
| [agent.md](./agent.md) | Agent 开发规范 |
| [a2a.md](./a2a.md) | A2A 协议落地说明 |

---

## 18. 结论

**v1.0 成功标准：** 证明下面这条链真正跑通——

```
一个任务 → 自动拆解 → 自动发现 Agent → 自动路由
        → A2A 调用 → 多 Agent 协作 → 结果聚合
```

最值得投入的不是协议细节本身，而是：

> **Planner + Agent Registry + Router + Scheduler + Task DAG + Observability**

A2A 解决「怎么说话」；本平台解决「为什么找这个 Agent、怎么拆、怎么调度、失败怎么办、结果怎么组合」。
