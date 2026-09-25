# Build from monorepo root:
#   docker build -f agents/harness-agent/Dockerfile .
FROM python:3.12-slim

WORKDIR /app

# Install local packages first (llm-provider + agent-runtime)
COPY packages/llm-provider /tmp/llm-provider
COPY packages/agent-runtime /tmp/agent-runtime
RUN pip install --no-cache-dir /tmp/llm-provider /tmp/agent-runtime[harness] \
    && rm -rf /tmp/llm-provider /tmp/agent-runtime

COPY agents/harness-agent/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY agents/harness-agent /app

ENV HARNESS_PROFILE=claude-coder
ENV PORT=8011
EXPOSE 8011

CMD ["sh", "-c", "uvicorn agent:app --host 0.0.0.0 --port ${PORT}"]
