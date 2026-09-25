PYTHON ?= python
IMAGE ?= rag-platform:0.2.0

.PHONY: check reproduce docker-build docker-smoke clean

check:
	$(PYTHON) -m compileall -q rag_platform tests
	$(PYTHON) -m unittest discover -s tests -v

reproduce:
	$(PYTHON) -m rag_platform answer --question "How does the retrieval service abstain?" --output artifacts/answer.json
	$(PYTHON) -m rag_platform answer --question "What is the capital of France?" --output artifacts/abstention.json --trace-output artifacts/traces.jsonl
	$(PYTHON) -m rag_platform evaluate --output artifacts/evaluation.json
	$(PYTHON) -m rag_platform evaluate --education-dir data/education_fixture --release synthetic-fixture --output artifacts/education-fixture-evaluation.json

docker-build:
	docker build -t $(IMAGE) .

docker-smoke: docker-build
	docker compose --profile fixture up -d --wait
	$(PYTHON) -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5).read().decode())"
	docker compose --profile fixture down

clean:
	$(PYTHON) -c "import shutil; shutil.rmtree('artifacts', ignore_errors=True)"
