from __future__ import annotations

import argparse
import json
from pathlib import Path

from .service import answer
from .tracing import append_trace, trace


def main() -> None:
    parser = argparse.ArgumentParser(description="Cited RAG reference with safety and trace artifacts.")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trace-output", type=Path, help="Optional local JSONL metadata trace sink.")
    args = parser.parse_args()
    result = answer(args.question, json.loads(args.corpus.read_text(encoding="utf-8")))
    trace_record = trace(args.question, result)
    payload = {"result": result, "trace": trace_record}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if args.trace_output:
        append_trace(args.trace_output, trace_record)
    print(json.dumps({"status": result["status"], "output": str(args.output)}, indent=2))


if __name__ == "__main__":
    main()
