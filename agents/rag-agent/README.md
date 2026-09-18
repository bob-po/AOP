# RAG Agent

Enterprise knowledge retrieval with **hybrid TF-IDF vector + keyword** ranking (Phase 16).

## Corpus

`knowledge/corpus.json` — edit documents and restart the agent to rebuild the in-memory index.

## Env

| Variable | Default | Meaning |
|----------|---------|---------|
| `RAG_TOP_K` | `3` | Citations returned |
| `RAG_HYBRID_ALPHA` | `0.65` | Weight of cosine vs keyword |

## Run

```bash
pip install -r requirements.txt
python agent.py
# :8002
```

Outputs: `rag-answer` (text) + `rag-citations` (JSON with `score` / `vector_score`).
