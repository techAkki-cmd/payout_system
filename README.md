# User Payout Management System

Phase 1 establishes the base FastAPI service layout, PostgreSQL connectivity, Docker support, and environment configuration.

## Requirements

- Python 3.11+
- Docker and Docker Compose
- PostgreSQL 15 when running outside Docker

## Local Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

## Docker Setup

```bash
docker compose up --build
```

The `web` service waits for the PostgreSQL healthcheck before starting.
PostgreSQL is exposed on host port `5433` to avoid colliding with a local database.

## Health Check

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "healthy"}
```

## Project Layout

```text
payout_system/
├── app/
│   ├── api/v1/
│   ├── core/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   └── main.py
├── tests/
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```
