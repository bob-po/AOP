# PPT Agent (DeepPresenter / PPTAgent)

A2A agent on **:8009** with skill `ppt-generation`.

- **Backend:** DeepPresenter ([PPTAgent v1.1.38](https://github.com/icip-cas/PPTAgent/tree/v1.1.38)) via Docker / optional HTTP
- **Fallback:** local `python-pptx` stub (`PPT_MODE=auto`)

## Run locally

```bash
cd agents/ppt-agent
pip install -r requirements.txt
set PPT_MODE=stub
uvicorn agent:app --host 0.0.0.0 --port 8009
```

## Env

| Variable | Default | Meaning |
|----------|---------|---------|
| `PPT_MODE` | `auto` | `auto` / `deeppresenter` / `stub` |
| `PPTAGENT_GENERATE_URL` | empty | Optional HTTP generate base |
| `PPTAGENT_CONTAINER` | `aop-deeppresenter` | Docker container for `pptagent generate` |
| `PPTAGENT_TIMEOUT` | `600` | Seconds |

DeepPresenter setup: see [deployments/pptagent/README.md](../../deployments/pptagent/README.md).
