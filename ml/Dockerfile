FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml ./
COPY agent_review ./agent_review
RUN pip install --no-cache-dir .
COPY examples ./examples
COPY tests ./tests
ENTRYPOINT ["python", "-m", "agent_review"]
CMD ["--help"]
