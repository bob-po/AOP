# Search Agent

A2A web-search agent for AOP research DAGs.

## Modes (`SEARCH_MODE`)

| Value | Behavior |
|-------|----------|
| `auto` (default) | DuckDuckGo Instant → DDG HTML-lite → Wikipedia → mock |
| `live` | Same live backends, mock only if all fail |
| `wiki` | Wikipedia OpenSearch only (+ mock fallback) |
| `mock` | Deterministic offline results |

Optional: `SEARCH_LIMIT` (default 5), `SEARCH_WIKI_LANG` (default `en`).

## Run

```bash
pip install -r requirements.txt
python agent.py
# :8001
```

Health: `GET /health` reports `search_mode`.
