FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent-card.json .
COPY agent.py .
ENV PORT=8004
ENV AGENT_URL=http://0.0.0.0:8004/
EXPOSE 8004
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8004"]
