# Phase 37 摘要

**主题：** 统一 LLM Provider + Agent Runtime  
**结论：** 已落地为可复用包；细节以包内 README 为准。

## 交付物

| 包 | 说明 |
|----|------|
| `packages/llm-provider` | OpenAI 兼容 Provider、Mock、重试与用量观测 |
| `packages/agent-runtime` | Tool registry、调用循环、超时与迭代限制 |

配置与接入见各包 `README.md`。E2E 脚本：`apps/orchestrator/scripts/phase37_e2e_validation.py`（结果写入本目录 `e2e-validation-results.json`，按需生成、不入库）。

返回 [文档中心](../../README.md)。
