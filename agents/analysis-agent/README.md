# Analysis Agent

A2A agent exposing skill `business-analysis` (Planner pipeline middle node).

```bash
cd agents/analysis-agent
pip install -r requirements.txt
uvicorn agent:app --host 0.0.0.0 --port 8004
```
