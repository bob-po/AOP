FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt* pyproject.toml* ./
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; \
    else pip install --no-cache-dir fastapi uvicorn flask; fi
COPY . .
ENV PORT=8000
EXPOSE 8000
CMD ["python", "-c", "import os; print('Set CMD for your app')"]
