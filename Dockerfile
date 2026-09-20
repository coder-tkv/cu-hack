FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY ml/pyproject.toml ./ml/pyproject.toml
COPY ml/agent_review ./ml/agent_review
RUN uv sync --frozen --no-cache --no-dev

COPY src ./src

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/src

WORKDIR /app/src
RUN chmod +x prestart.sh
ENTRYPOINT ["./prestart.sh"]

EXPOSE 8080
