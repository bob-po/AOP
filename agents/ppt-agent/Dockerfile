FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent-card.json .
COPY agent.py ppt_backend.py deeppresenter_client.py stub_pptx.py ./
ENV PORT=8009
ENV AGENT_URL=http://0.0.0.0:8009/
ENV PPT_MODE=auto
EXPOSE 8009
CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8009"]
