---
name: python-deployment
description: Build and run Python web apps (FastAPI, Flask, Django) in Docker.
---

# Python Deployment Skill

Defaults:

- Base image: `python:3.12-slim`
- Install deps: `pip install -r requirements.txt` (or poetry export if needed)
- FastAPI: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Flask: `gunicorn -b 0.0.0.0:$PORT app:app` or `python app.py`
- Django: `python manage.py migrate && gunicorn project.wsgi:application -b 0.0.0.0:$PORT`
- Default port: 8000 when unspecified

Common repairs:

- Missing dependency in requirements.txt
- Wrong module path for uvicorn/gunicorn
- Binding to 127.0.0.1 instead of 0.0.0.0
