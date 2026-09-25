from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from .education_corpus import RELEASES, ReleaseRejected, load_education_corpus, read_semantic_records
from .evaluation import education_cases, evaluate_abstention, evaluate_retrieval
from .gateway import ChatGateway, PriceTable, routes_from_env
from .generation import ExtractiveGenerator, GatewayGenerator, Generator
from .ingestion import Document, load_fixture_documents
from .observability import Exporter, JsonlExporter, LangfuseExporter, NoExporter
from .service import RagService, build_service


DEFAULT_CORPUS = Path("data/corpus_fixture.json")


def _add_corpus_arguments(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--corpus", type=Path, help=f"Fixture corpus JSON (default: {DEFAULT_CORPUS}).")
    source.add_argument("--education-dir", type=Path, help="Unpacked education release directory.")
    parser.add_argument("--release", choices=sorted(RELEASES), default="v1", help="Pinned education release to accept.")
    parser.add_argument("--retrieval", choices=("bm25", "hybrid"), default="bm25")
    parser.add_argument("--generator", choices=("extractive", "gateway"), default="extractive")
    parser.add_argument("--price-table", type=Path, help="JSON price table for gateway cost attribution.")
    parser.add_argument("--trace-export", choices=("none", "jsonl", "langfuse"), default="none")
    parser.add_argument("--trace-output", type=Path, help="JSONL trace sink; implies --trace-export jsonl.")
    parser.add_argument("--trace-include-content", action="store_true", help="Export passage and answer text (off by default).")


def load_documents(args: argparse.Namespace) -> list[Document]:
    if args.education_dir:
        return load_education_corpus(args.education_dir, RELEASES[args.release])
    return load_fixture_documents(args.corpus or DEFAULT_CORPUS)


def build_generator(args: argparse.Namespace) -> Generator:
    if args.generator == "extractive":
        return ExtractiveGenerator()
    routes = routes_from_env()
    if not routes:
        raise SystemExit("--generator gateway requires RAG_GATEWAY_BASE_URL (see .env.example)")
    price_path = args.price_table or (Path(os.environ["RAG_PRICE_TABLE"]) if os.environ.get("RAG_PRICE_TABLE") else None)
    prices = PriceTable.from_json(price_path) if price_path else PriceTable({})
    return GatewayGenerator(ChatGateway(routes, prices))


def build_exporter(args: argparse.Namespace) -> Exporter:
    mode = "jsonl" if args.trace_output else args.trace_export
    if mode == "jsonl":
        return JsonlExporter(args.trace_output or Path("artifacts/traces.jsonl"), args.trace_include_content)
    if mode == "langfuse":
        host = os.environ.get("LANGFUSE_HOST")
        if not host:
            raise SystemExit("--trace-export langfuse requires LANGFUSE_HOST")
        return LangfuseExporter(host, allow_content=args.trace_include_content)
    return NoExporter()


def build_from_args(args: argparse.Namespace) -> tuple[RagService, list[Document]]:
    documents = load_documents(args)
    service = build_service(documents, args.retrieval, generator=build_generator(args), exporter=build_exporter(args))
    return service, documents


def _write(payload: dict[str, Any], output: Path | None) -> None:
    text = json.dumps(payload, indent=2) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
    sys.stdout.write(text)


def command_answer(args: argparse.Namespace) -> None:
    service, _ = build_from_args(args)
    payload: dict[str, Any] = {"result": service.answer(args.question)}
    if isinstance(service.exporter, NoExporter):
        payload["trace"] = service.exporter.exported[-1]
    _write(payload, args.output)


def command_evaluate(args: argparse.Namespace) -> None:
    service, _ = build_from_args(args)
    if args.education_dir:
        cases = education_cases(read_semantic_records(args.education_dir), args.max_municipalities)
    else:
        cases = json.loads((args.cases or Path("data/evaluation_fixture.json")).read_text(encoding="utf-8"))
    payload = {"retrieval": evaluate_retrieval(service, cases, args.k), "abstention": evaluate_abstention(service)}
    _write(payload, args.output)


def command_serve(args: argparse.Namespace) -> None:
    from .api import make_server

    service, documents = build_from_args(args)
    health = {"documents": len(documents), "retrieval": args.retrieval, "generator": args.generator}
    server = make_server(service, args.host, args.port, health)
    print(json.dumps({"listening": f"http://{args.host}:{server.server_address[1]}"}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="rag-platform", description="Cited RAG reference with safety, evaluation, and trace artifacts.")
    commands = root.add_subparsers(dest="command", required=True)
    answer = commands.add_parser("answer", help="Answer one question with citations or abstain.")
    _add_corpus_arguments(answer)
    answer.add_argument("--question", required=True)
    answer.add_argument("--output", type=Path)
    answer.set_defaults(handler=command_answer)
    evaluate = commands.add_parser("evaluate", help="Run recall@k, citation coverage, and abstention evaluation.")
    _add_corpus_arguments(evaluate)
    evaluate.add_argument("--cases", type=Path, help="Labeled cases for a fixture corpus.")
    evaluate.add_argument("--k", type=int, default=3)
    evaluate.add_argument("--max-municipalities", type=int, help="Deterministic sample size for education evaluation.")
    evaluate.add_argument("--output", type=Path)
    evaluate.set_defaults(handler=command_evaluate)
    serve = commands.add_parser("serve", help="Serve the JSON API.")
    _add_corpus_arguments(serve)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.set_defaults(handler=command_serve)
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        args.handler(args)
    except ReleaseRejected as exc:
        raise SystemExit(f"education release rejected: {exc}") from None


if __name__ == "__main__":
    main()
