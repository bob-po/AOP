# Browser Agent (Phase 27 + 29)

`browser-automation` skill with:

- **stub** (default slim image) — metadata only
- **playwright** — headless Chromium when installed (`BROWSER_MODE=auto|playwright`)

## Env

| 变量 | 默认 | 说明 |
|------|------|------|
| `BROWSER_MODE` | `auto` | `stub` / `playwright` / `auto` |
| `BROWSER_EGRESS_ALLOWLIST` | 空 | 逗号 host / `*.suffix` |
| `BROWSER_TIMEOUT_MS` | `15000` | 导航超时 |
| `BROWSER_SCREENSHOT` | `0` | `1` 时尝试 PNG base64 |

## Local (stub)

```bash
pip install -r requirements.txt
BROWSER_MODE=stub uvicorn agent:app --port 8008
```

## Local (Chromium)

```bash
pip install -r requirements-playwright.txt
playwright install chromium
BROWSER_MODE=playwright uvicorn agent:app --port 8008
```

## Docker

```bash
# slim stub
docker build -t aop-browser-agent .

# Chromium image
docker build -f Dockerfile.chromium -t aop-browser-chromium .
```

Compose default uses slim + `BROWSER_MODE=stub`（或 `auto` 无 playwright 时回退）。
启用 Chromium 服务见 `deployments/docker-compose.browser-chromium.yml`。
