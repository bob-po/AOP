# DeerFlow (AOP search-agent backend)

Vendored upstream: [bytedance/deer-flow](https://github.com/bytedance/deer-flow) **main-1.x**.

## Setup

```bash
# from repo root
git clone --depth 1 --branch main-1.x https://github.com/bytedance/deer-flow.git third_party/deer-flow

cp deployments/deerflow/.env.example deployments/deerflow/.env
# conf.yaml uses $OPENAI_* env placeholders (no secrets committed)
```

Set in the shell **before** `docker compose up` (or point at local New API on `:3001`):

```powershell
$env:OPENAI_API_KEY = "sk-..."          # DeepSeek / New API token
$env:OPENAI_BASE_URL = "https://api.deepseek.com"   # or http://host.docker.internal:3001/v1
$env:OPENAI_MODEL = "deepseek-chat"
docker compose -f deployments/docker-compose.yml --profile deerflow up -d --force-recreate deerflow
```

Without `OPENAI_API_KEY`, DeerFlow starts but research calls fail (`Error during graph execution`); search-agent falls back to Bing/Wikipedia.

## Run

```bash
docker compose -f deployments/docker-compose.yml --profile deerflow up -d --build deerflow
# API: http://127.0.0.1:8020
```

```powershell
$env:DEERFLOW_URL = "http://127.0.0.1:8020"
$env:SEARCH_MODE = "auto"
$env:SEARCH_FETCH_PAGES = "3"
```
