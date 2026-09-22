# Search Agent

A2A web-search agent for AOP research DAGs.

## Modes (`SEARCH_MODE`)

| Value | Behavior |
|-------|----------|
| `auto` (default) | **DeerFlow** (if `DEERFLOW_URL`) → Bing → DDG Instant → DDG HTML-lite → Wikipedia → mock |
| `deerflow` | DeerFlow only (+ mock fallback) |
| `live` | Live backends (DeerFlow first when configured), mock only if all fail |
| `wiki` | Wikipedia OpenSearch only (+ mock fallback) |
| `mock` | Deterministic offline results |

Optional: `SEARCH_LIMIT` (default 5), `SEARCH_WIKI_LANG` (default `en`).

### DeerFlow backend

Uses [bytedance/deer-flow](https://github.com/bytedance/deer-flow) **main-1.x** Deep Research API (`POST /api/chat/stream`).

| Env | Default | Meaning |
|-----|---------|---------|
| `DEERFLOW_URL` | _(empty)_ | DeerFlow base URL, e.g. `http://127.0.0.1:8020` |
| `DEERFLOW_TIMEOUT` | `300` | Stream timeout (seconds) |
| `DEERFLOW_MAX_SEARCH_RESULTS` | `SEARCH_LIMIT` | Passed to DeerFlow |
| `DEERFLOW_MAX_STEP_NUM` | `3` | DeerFlow plan steps |
| `DEERFLOW_REPORT_STYLE` | `ACADEMIC` | Report style enum |
| `DEERFLOW_LOCALE` | `zh-CN` | Locale |

After search hits are returned (non-DeerFlow backends), the agent opens the top pages and extracts readable text:

| Env | Default | Meaning |
|-----|---------|---------|
| `SEARCH_FETCH_PAGES` | `3` | How many top URLs to open (`0` disables) |
| `SEARCH_FETCH_CHARS` | `2500` | Max characters kept per page |
| `SEARCH_FETCH_TIMEOUT` | `10` | Per-page HTTP timeout (seconds) |

`url-fetch` skill fetches a single URL without searching.

## Run

```bash
pip install -r requirements.txt
# Optional DeerFlow (host):
#   export DEERFLOW_URL=http://127.0.0.1:8020
python agent.py
# :8001
```

Docker (with DeerFlow):

```bash
# once
git clone --depth 1 --branch main-1.x https://github.com/bytedance/deer-flow.git third_party/deer-flow
cp deployments/deerflow/.env.example deployments/deerflow/.env
cp deployments/deerflow/conf.yaml.example deployments/deerflow/conf.yaml
# edit .env (SEARCH_API / TAVILY_API_KEY) and conf.yaml (BASIC_MODEL)

docker compose -f deployments/docker-compose.yml --profile agents up -d --build deerflow search-agent
```

Health: `GET /health` reports `search_mode`.
