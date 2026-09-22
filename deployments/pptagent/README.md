# DeepPresenter / PPTAgent (AOP ppt-agent backend)

Vendored upstream: [icip-cas/PPTAgent](https://github.com/icip-cas/PPTAgent) tag **v1.1.38** (DeepPresenter runtime).  
Current `main` is a coding-agent Skill only — do **not** use it for A2A.

Official note: native Windows CLI is unsupported; use **Docker Desktop**.

## Setup

```bash
# from repo root
git clone --depth 1 --branch v1.1.38 https://github.com/icip-cas/PPTAgent.git third_party/PPTAgent

cp deployments/pptagent/config.yaml.example deployments/pptagent/config.yaml
# Edit config.yaml: set research_agent / design_agent api_key + base_url (OpenAI-compatible)

# Pull published images (or build from third_party/PPTAgent)
docker pull forceless/deeppresenter-host
docker pull forceless/deeppresenter-sandbox
docker tag forceless/deeppresenter-host deeppresenter-host
docker tag forceless/deeppresenter-sandbox deeppresenter-sandbox
```

## Run

```bash
docker compose -f deployments/docker-compose.yml --profile pptagent up -d deeppresenter
# Gradio UI: http://127.0.0.1:8021
```

Point the A2A wrapper at the container:

```powershell
$env:PPT_MODE = "auto"
$env:PPTAGENT_CONTAINER = "aop-deeppresenter"
```

Without the container, `ppt-agent` still serves real `.pptx` via the python-pptx stub.
