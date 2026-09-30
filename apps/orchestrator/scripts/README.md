# Orchestrator smoke / e2e scripts

Most `phase*.py` files were one-shot delivery checks. Prefer:

| Goal | Command |
|------|---------|
| Unit / integration | `pytest -q apps/orchestrator/tests` |
| Harness e2e | `python scripts/e2e_harness_validation.py` |
| Live feature smoke | remaining `phase*.py` (auth, billing, …) until folded into tests |

Thin wrappers (`phase13`, `phase19`, `phase37`) print a deprecation note and forward.
