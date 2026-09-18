FROM python:3.12-slim

WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin aop \
 && mkdir -p /tmp/aop && chown -R aop:aop /tmp/aop

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent-card.json .
COPY agent.py .

ENV PORT=8007
ENV AGENT_URL=http://0.0.0.0:8007/
ENV AOP_SECCOMP_PROFILE=code-agent
ENV HOME=/tmp/aop
ENV PYTHONDONTWRITEBYTECODE=1

USER 10001:10001
EXPOSE 8007

CMD ["uvicorn", "agent:app", "--host", "0.0.0.0", "--port", "8007"]
