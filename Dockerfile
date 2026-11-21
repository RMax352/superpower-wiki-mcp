FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY superpower_wiki_mcp ./superpower_wiki_mcp

RUN pip install --no-cache-dir .

ENV HOST=0.0.0.0
ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "uvicorn superpower_wiki_mcp.server:app --host 0.0.0.0 --port ${PORT:-8080}"]
