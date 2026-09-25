# Base image pinned by digest; update the digest deliberately, not by tag drift.
FROM python:3.12-slim@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY rag_platform ./rag_platform
RUN pip install --root-user-action=ignore . \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin rag

# The corpus is not baked in; mount it read-only at /data.
USER 10001
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2)"]
ENTRYPOINT ["rag-platform"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8080", "--corpus", "/data/corpus_fixture.json"]
