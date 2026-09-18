FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent-card.json .
COPY agent.py .
COPY knowledge ./knowledge
ENV PORT=8002
ENV AGENT_URL=http://0.0.0.0:8002/
EXPOSE 8002
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8002"]
