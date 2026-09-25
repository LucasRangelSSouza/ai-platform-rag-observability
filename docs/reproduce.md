# Reproduce

Everything below runs offline except the optional education v1 download and the optional live profiles at the end.

## Environment

Python 3.10 or newer (the recorded runs used 3.12.3 on Windows and 3.12.14 in the container). The only runtime dependency is `pyarrow==18.1.0`.

```bash
python -m venv .venv
. .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -e .
make check
make reproduce
```

`make reproduce` writes five files to `artifacts/`:

| File | Expected content |
|---|---|
| `answer.json` | `"status": "answered"`, one citation to `safety#c000`, a redacted trace |
| `abstention.json` | `"status": "abstained"`, `"safety_reason": "insufficient_retrieval"` |
| `traces.jsonl` | one appended line per run, with `question_sha256` and no question text |
| `evaluation.json` | fixture `recall_at_k` 1.0, `citation_coverage` 1.0, abstention rate 1.0 |
| `education-fixture-evaluation.json` | 7 cases, recall 1.0, citation coverage 1.0, abstention rate 0.833333 |

Without `make`, run the commands listed under `reproduce` in the `Makefile` directly. On Windows, `make check PYTHON="py -3.12"` selects the interpreter.

## Education release v1

Download the pinned release and point the CLI at the unpacked directory:

```bash
python -c "import kagglehub; print(kagglehub.dataset_download('lucasrangelss/brazil-education-data-lake/versions/1'))"
python -m rag_platform evaluate --education-dir <printed path> --release v1 --max-municipalities 250
```

The adapter checks that `release_manifest.json` hashes to `44f259602a688432dddbae6b0306a6957514a634d57d94a0abd3cff30f4b3506` before reading anything. The full run takes a few minutes in pure Python; see `docs/evidence/` for the recorded timing.

## Container

```bash
docker build -t rag-platform:0.2.0 .
docker compose --profile fixture up -d --wait
curl -s http://127.0.0.1:8080/healthz
curl -s -X POST http://127.0.0.1:8080/v1/answer -d '{"question":"How does the retrieval service abstain?"}'
docker compose --profile fixture down
```

The education profile serves an unpacked release from `EDUCATION_RELEASE_DIR` on port 8081, mounted read-only. It defaults to the synthetic fixture directory, so set `EDUCATION_RELEASE=synthetic-fixture` when you do not supply the v1 release.

## Optional live profiles

These need services you run yourself. Copy `.env.example` to `.env` and fill only what you use.

- Gateway: set `RAG_GATEWAY_BASE_URL` and `RAG_GATEWAY_MODEL`, then pass `--generator gateway`. Add `--price-table config/prices.example.json` after replacing its example values with your provider's prices.
- Langfuse: set `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY`, then pass `--trace-export langfuse`.

## Cleanup

`make clean` removes `artifacts/`. `docker compose --profile fixture down` and `docker image rm rag-platform:0.2.0` remove the container state.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `education release rejected: manifest SHA-256 does not match` | The directory is not the pinned release, or a file was edited. Re-download; do not change the pin to match local files. |
| `release file ... does not match its manifest SHA-256` on the synthetic fixture | Git converted line endings. `.gitattributes` marks `data/education_fixture/**` as `-text`; re-checkout that directory. |
| `ModuleNotFoundError: pyarrow` | Install the package with `pip install -e .`. Fixture mode imports pyarrow only for education corpora. |
| `--generator gateway requires RAG_GATEWAY_BASE_URL` | Expected in fixture mode; set the variable or use the default extractive generator. |
| Port 8080 already in use | Stop the other service or change the host port in `docker-compose.yml`. |
| Gateway tests take several seconds on Windows | One test connects to a closed local port, and Windows retries refused connections before failing. |
