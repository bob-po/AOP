#!/usr/bin/env python3
"""Phase 1 smoke: discover Search Agent card and call message/send."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ORCH_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
SDK_ROOT = REPO_ROOT / "packages" / "a2a-sdk"

for path in (ORCH_ROOT, SDK_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from a2a_sdk import A2AClient  # noqa: E402
from executor import A2AExecutor  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Call Search Agent via A2A")
    parser.add_argument("--url", default="http://127.0.0.1:8001", help="Agent base URL")
    parser.add_argument("--query", default="AI Agent Orchestration", help="Search query")
    parser.add_argument("--skill", default="web-search", help="Skill id")
    parser.add_argument("--json", action="store_true", help="Print compact task JSON")
    args = parser.parse_args()

    print(f"[1/3] Discovering Agent Card at {args.url} ...")
    client = A2AClient(args.url)
    card = client.card
    print(f"      name={card.name!r} version={card.version} skills={card.skill_ids()}")

    print(f"[2/3] Sending message/send query={args.query!r} skill={args.skill!r} ...")
    executor = A2AExecutor()
    result = executor.execute(args.url, args.query, skill_id=args.skill)

    print(f"[3/3] Task id={result.task.id} status={result.task.status.value}")
    if result.text:
        print("--- text artifact ---")
        print(result.text)
    if result.data:
        print("--- data artifact ---")
        print(json.dumps(result.data, ensure_ascii=False, indent=2))

    if args.json:
        print("--- task summary ---")
        print(
            json.dumps(
                {
                    "id": result.task.id,
                    "status": result.task.status.value,
                    "artifact_count": len(result.task.artifacts),
                    "metadata": result.task.metadata,
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
