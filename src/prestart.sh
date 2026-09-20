#!/usr/bin/env sh

set -e

echo "Run apply migrations..."
alembic upgrade head
echo "Migrations applied!"

exec uvicorn main:app --host 0.0.0.0 --port 8080