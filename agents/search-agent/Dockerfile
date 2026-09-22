FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# Docker image only needs FastAPI search stack; optional LLM extras install separately on host.
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" httpx beautifulsoup4 lxml

COPY *.py ./
COPY agent-card.json .

ENV PORT=8001
ENV AGENT_URL=http://0.0.0.0:8001/
ENV SEARCH_MODE=auto

EXPOSE 8001

CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8001"]
