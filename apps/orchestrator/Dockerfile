# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /workspace

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/*

COPY packages/a2a-sdk /workspace/packages/a2a-sdk
COPY apps/orchestrator /workspace/apps/orchestrator
COPY infrastructure/postgres /workspace/infrastructure/postgres

RUN pip install -i "${PIP_INDEX_URL}" --upgrade pip \
  && pip install -i "${PIP_INDEX_URL}" -e /workspace/packages/a2a-sdk \
  && pip install -i "${PIP_INDEX_URL}" -r /workspace/apps/orchestrator/requirements.txt

WORKDIR /workspace/apps/orchestrator
# Support dynamic port configuration
EXPOSE 8090 8091 8092
CMD ["python", "main.py"]
