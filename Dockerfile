FROM ghcr.io/astral-sh/uv:0.12.15 AS uv
FROM python:3.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home app && mkdir /data && chown app:app /data
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE NOTICE.md ./
COPY vendor/bilibili-mcp/LICENSE /app/licenses/AGI_Ananas-LICENSE
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 BILI_DATA_DIR=/data HF_HOME=/data/huggingface BILI_MODEL_DIR=/data/models
USER 10001:10001
EXPOSE 8888
HEALTHCHECK --interval=30s --timeout=5s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8888/health', timeout=3)"]
CMD ["bilibili-mcp"]
