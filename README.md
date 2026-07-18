# Creator Payout Operations Console

![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0-D71F00)
![pytest](https://img.shields.io/badge/pytest-tested-0A9EDC)

A production-oriented payout management system for creator platforms. It protects creator trust and platform retention by making payouts accurate, idempotent, auditable, and resilient to duplicate jobs, concurrent withdrawal attempts, and failed bank or UPI transfers.

The system models each wallet movement through an append-only ledger, uses PostgreSQL row-level locking for financial writes, and exposes a clean FastAPI backend with a lightweight dashboard for reviewer demos.

## What It Solves

Creator marketplaces often need to pay creators before a sale is fully reconciled. This system supports that workflow safely:

- Pay a **10% advance** for pending sales.
- Guarantee an advance is applied **only once** per sale.
- Reconcile sales as **approved** or **rejected** with exact Decimal math.
- Enforce a **24-hour withdrawal lock**.
- Recover failed withdrawals back to the creator wallet.
- Validate wallet balance against the append-only ledger.

## Quick Start With Docker

```bash
cd /Users/arijitajaykumar/Documents/payout_system
docker compose up --build -d
```

The Docker stack starts:

- `db`: PostgreSQL 15 on host port `5433`
- `web`: FastAPI on `http://localhost:8000`

The compose setup enables `AUTO_CREATE_TABLES=true` for reviewer/demo convenience. Production deployments should use migrations instead of automatic table creation.

## Access The App

| Surface | URL |
| --- | --- |
| Dashboard | `http://localhost:8000/` |
| Swagger API Docs | `http://localhost:8000/docs` |
| Health Check | `http://localhost:8000/health` |

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Expected response:

```json
{"status":"healthy"}
```

## Local Development

```bash
cd /Users/arijitajaykumar/Documents/payout_system
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Run the API locally:

```bash
uvicorn app.main:app --reload
```

Run quality checks:

```bash
.venv/bin/ruff check .
.venv/bin/python -m pytest -q
```

The test suite verifies payout math, ledger integrity, API behavior, worker idempotency, failed payout recovery, and concurrency protection.

## Dashboard Demo Flow

Open `http://localhost:8000/` and run this reviewer-friendly flow:

1. Create a creator, for example `mumbai_creator`.
2. Add an Indian campaign sale, for example `Jaipur Kurti Co` with earnings `100.00`.
3. Click **Run 10% Advance Payout Worker**.
4. Wallet should show `INR 10.00`.
5. Approve the sale.
6. Wallet should show `INR 100.00` because final payout is `100.00 - 10.00`.
7. Withdraw `50.00`.
8. Wallet should show `INR 50.00` and the withdrawal should enter `INITIATED`.
9. Simulate UPI/bank failure.
10. Wallet should return to `INR 100.00`, with both the failed withdrawal and recovery credit visible in the ledger.
11. Click **Validate Wallet Integrity** to confirm the cached wallet balance matches the ledger sum.

## API Overview

All versioned API routes are mounted under `/api/v1`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/users/` | Create a demo creator wallet. |
| `GET` | `/api/v1/users/{user_id}` | Fetch wallet balance and withdrawal lock state. |
| `POST` | `/api/v1/sales/` | Ingest a new pending sale for an existing creator. |
| `GET` | `/api/v1/sales/{user_id}` | List sales for a creator. |
| `POST` | `/api/v1/payouts/advance/trigger` | Manually trigger the 10% advance payout worker. |
| `POST` | `/api/v1/reconciliation/{sale_id}` | Reconcile a sale as `APPROVED` or `REJECTED`. |
| `POST` | `/api/v1/withdrawals/` | Initiate a creator withdrawal. |
| `POST` | `/api/v1/webhooks/withdrawals/failed` | Simulate gateway failure and recover funds. |
| `GET` | `/api/v1/transactions/{user_id}` | List append-only ledger entries for a creator. |
| `GET` | `/api/v1/audit/wallet/{user_id}` | Validate wallet balance against ledger totals. |

## Core Financial Rules

| Rule | Implementation |
| --- | --- |
| Money precision | `Decimal` values persisted as `Numeric(10, 2)`. |
| Advance payout | `earnings * 0.10`, quantized to `0.01`. |
| Advance idempotency | `sales.is_advance_processed` guarded by row locks. |
| Approved sale | Credits `earnings - advance_paid`. |
| Rejected sale | Debits `advance_paid`, allowing negative balances for clawbacks. |
| Withdrawal limit | One withdrawal per creator per 24 hours. |
| Failed withdrawal recovery | Credits back the absolute withdrawal amount once. |
| Ledger audit | Sum of ledger entries must equal `users.withdrawable_balance`. |

## Project Layout

```text
payout_system/
├── app/
│   ├── api/v1/endpoints/     # FastAPI route handlers
│   ├── core/                 # Settings, DB sessions, wallet audit
│   ├── models/               # SQLAlchemy 2.0 ORM models
│   ├── schemas/              # Pydantic V2 request/response schemas
│   ├── services/             # Transactional business logic
│   ├── static/index.html     # Single-page dashboard
│   ├── workers/              # Batch payout and recovery workers
│   └── main.py
├── tests/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── README.md
└── SYSTEM_DESIGN.md
```

## Design Deep-Dive

See [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md) for the architecture, data model, locking strategy, recovery flow, trade-offs, and scaling plan.
