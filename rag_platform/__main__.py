from __future__ import annotations

import argparse
import json
from pathlib import Path

from .service import answer
from .tracing import trace


def main() -> None:
    parser = argparse.ArgumentParser(description="Cited RAG reference with safety and trace artifacts.")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = answer(args.question, json.loads(args.corpus.read_text(encoding="utf-8")))
    payload = {"result": result, "trace": trace(args.question, result)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
