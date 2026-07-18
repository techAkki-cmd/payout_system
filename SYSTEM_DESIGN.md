# System Design: Creator Payout Operations Console

## 1. Architecture Overview

The system is a FastAPI and PostgreSQL financial workflow service for managing creator payouts. It is intentionally compact enough for an assignment submission, but its core design follows the same reliability principles used in financial microservices: exact arithmetic, transactional writes, idempotent workers, append-only audit history, and explicit recovery paths.

```text
Dashboard / Reviewer
        |
        v
FastAPI API Layer
        |
        v
Service Layer
        |
        v
SQLAlchemy 2.0 Unit of Work
        |
        v
PostgreSQL 15
```

### Technology Choices

| Component | Choice | Rationale |
| --- | --- | --- |
| API framework | FastAPI | Strong typing, OpenAPI generation, dependency injection, and clean request validation. |
| Database | PostgreSQL 15 | ACID transactions, row-level locks, `SELECT FOR UPDATE`, and production-grade durability. |
| ORM | SQLAlchemy 2.0 | Explicit unit-of-work control and modern typed ORM models. |
| Validation | Pydantic V2 | Strict request and response schemas for Decimal money values and UUID identifiers. |
| Runtime | Docker Compose | Reproducible local reviewer environment with FastAPI and PostgreSQL. |
| UI | Static HTML + Tailwind + vanilla JS | Zero frontend build pipeline while still providing an interactive evaluator dashboard. |

The API is the source of truth. The dashboard is a thin operational client that drives existing endpoints and visualizes wallet, sale, and ledger state.

## 2. Domain Model

### User Wallet

`users.withdrawable_balance` stores the current wallet balance. It is a cached operational balance used for fast reads and withdrawal checks. The authoritative explanation for how that balance changed lives in the ledger.

Important fields:

- `username`: unique creator identifier for demo and lookup.
- `withdrawable_balance`: `Numeric(10, 2)` mapped to Python `Decimal`.
- `last_withdrawal_at`: timestamp used to enforce the 24-hour withdrawal rule.

### Sale

`sales` represents creator earnings from brand campaigns or platform sales.

Important fields:

- `status`: `PENDING`, `APPROVED`, or `REJECTED`.
- `earnings`: exact sale earnings.
- `advance_paid`: amount already paid as the 10% advance.
- `is_advance_processed`: the idempotency guard that prevents duplicate advance credits.

Indexes on `sales.status` and `sales.is_advance_processed` support worker queries for pending, unprocessed sales.

### Transaction Ledger

`transactions` is the append-only ledger. Every wallet-impacting event creates a transaction row:

- Positive amounts are credits.
- Negative amounts are debits.
- Rows are not rewritten to represent new money movement.
- `reference_id` provides an idempotency key for external references and recovery entries.

Ledger transaction types:

- `ADVANCE_PAYOUT`
- `FINAL_PAYOUT`
- `RECONCILIATION_ADJUSTMENT`
- `WITHDRAWAL`
- `FAILED_RECOVERY`

This lets the system answer two separate questions:

1. What is the current wallet balance?
2. Why is that the correct balance?

## 3. Core Payout Flows

### 3.1 Advance Payout For Pending Sales

Pending sales receive a 10% advance:

```text
advance_amount = sale.earnings * Decimal("0.10")
```

The service:

1. Selects sales where `status = PENDING` and `is_advance_processed = false`.
2. Locks eligible sale rows using `SELECT FOR UPDATE SKIP LOCKED`.
3. Locks each user wallet row before crediting the balance.
4. Writes an `ADVANCE_PAYOUT` ledger entry.
5. Sets `advance_paid` and `is_advance_processed = true`.
6. Commits atomically.

`SKIP LOCKED` is the critical worker-scaling mechanism. If two worker instances run at the same time, each instance skips rows already locked by the other worker instead of blocking or double-processing the sale.

### 3.2 Sale Reconciliation

Admins reconcile a sale into a final state.

Approved sale:

```text
remaining = earnings - advance_paid
```

The user receives the remaining balance and the ledger records `FINAL_PAYOUT`.

Rejected sale:

```text
adjustment = -advance_paid
```

The advance is clawed back through a negative `RECONCILIATION_ADJUSTMENT`. The wallet is allowed to go negative because real payout systems often need to represent recoverable platform debt after rejection, refund, or fraud review.

Both reconciliation paths lock the sale row and user row with `SELECT FOR UPDATE` so concurrent updates serialize correctly.

### 3.3 Withdrawal

Withdrawals are guarded by both business rules and concurrency controls.

The service:

1. Acquires an in-process per-user lock for deterministic local protection.
2. Locks the PostgreSQL user row with `SELECT FOR UPDATE NOWAIT`.
3. Rejects non-positive amounts.
4. Enforces the 24-hour withdrawal lock.
5. Rejects insufficient funds.
6. Debits the wallet.
7. Updates `last_withdrawal_at`.
8. Creates a `WITHDRAWAL` transaction with status `INITIATED`.

`NOWAIT` makes the API fail fast with `409 Conflict` when another request is already mutating the wallet. That is better than letting users wait indefinitely or accidentally submit duplicate withdrawal attempts.

### 3.4 Failed Payout Recovery

If a bank, UPI, or payment gateway fails after a withdrawal has been initiated, the recovery service creates a compensating credit.

The service:

1. Locks the original withdrawal transaction.
2. Confirms it is a withdrawal and is eligible for recovery.
3. Builds a deterministic recovery idempotency key:

```text
failed_recovery:{withdrawal_id}
```

4. Rejects duplicate recovery attempts if that reference already exists.
5. Locks the user wallet.
6. Marks the original withdrawal as `FAILED`.
7. Credits back the absolute withdrawal amount.
8. Writes a `FAILED_RECOVERY` ledger row.

The original debit remains in the ledger. The recovery is represented as a separate credit, preserving a clear audit trail.

## 4. Concurrency And Idempotency Strategy

### Append-Only Ledger

The ledger is not merely a history table; it is the financial audit backbone. Direct balance mutation alone would be dangerous because it cannot explain historical movement or recover gracefully from gateway failures.

The design therefore uses:

- `users.withdrawable_balance` for fast operational reads.
- `transactions.amount` as the auditable balance trail.
- `GET /api/v1/audit/wallet/{user_id}` to compare the ledger sum against the cached balance.

### Advance Payout Idempotency

The `sales.is_advance_processed` flag is stored on the sale itself because the sale is the source event being paid. By locking the sale row before flipping this flag, concurrent workers coordinate through the database.

This protects against:

- Cron overlap.
- Manual trigger overlap from the dashboard.
- Multiple worker instances.
- Retry after partial failure.

### Pessimistic Locking

The system uses pessimistic locking because wallet writes are high-risk operations. Optimistic retries can work, but for payouts, explicit row locks are easier to reason about and safer under bursty concurrent requests.

Lock usage:

| Operation | Lock |
| --- | --- |
| Advance worker | `Sale.with_for_update(skip_locked=True)` and user row lock |
| Reconciliation | Sale row lock and user row lock |
| Withdrawal | User row lock with `nowait=True` |
| Recovery | Withdrawal transaction row lock and user row lock |

The in-process user wallet lock in the withdrawal service makes local SQLite-backed tests deterministic. PostgreSQL remains the production concurrency target.

## 5. Worker And Recovery Design

### Advance Payout Worker

The advance worker processes sales in batches. This avoids loading an unbounded number of pending sales into memory and gives the system a queue-friendly shape.

Current submission:

- Synchronous Python worker entrypoints.
- Batch size configurable by function argument.
- Uses `SKIP LOCKED` to allow multiple workers to divide work safely.

Production evolution:

- Trigger through Celery, RQ, RabbitMQ, Kafka, or a scheduler.
- Use metrics for processed count, failures, lock conflicts, and retry attempts.
- Add dead-letter events for repeated processing errors.

### Failed Withdrawal Recovery Worker

The recovery worker scans withdrawal transactions in terminal failed states:

- `FAILED`
- `CANCELLED`
- `REJECTED`

For each eligible transaction, it checks whether a deterministic recovery reference already exists. If not, it calls the recovery service to credit the user wallet and write a `FAILED_RECOVERY` ledger row.

This mimics a Dead Letter Queue pattern: failed external payout events are isolated, retried safely, and converted into compensating ledger entries.

## 6. API Surface

| Endpoint | Role |
| --- | --- |
| `POST /api/v1/users/` | Create a demo creator wallet. |
| `GET /api/v1/users/{user_id}` | Read wallet and withdrawal lock state. |
| `POST /api/v1/sales/` | Ingest a pending sale. |
| `GET /api/v1/sales/{user_id}` | List sales by creator. |
| `POST /api/v1/payouts/advance/trigger` | Trigger the advance payout worker manually. |
| `POST /api/v1/reconciliation/{sale_id}` | Approve or reject a sale. |
| `POST /api/v1/withdrawals/` | Initiate withdrawal. |
| `POST /api/v1/webhooks/withdrawals/failed` | Recover a failed withdrawal. |
| `GET /api/v1/transactions/{user_id}` | Inspect ledger rows. |
| `GET /api/v1/audit/wallet/{user_id}` | Validate ledger-to-wallet integrity. |

Routes intentionally stay thin. They validate HTTP input, handle structured error responses, and delegate financial decisions to the service layer.

## 7. Testing Strategy

The automated suite covers:

- Model metadata, enums, indexes, and Decimal money columns.
- 10% advance payout math and idempotency.
- Approved and rejected reconciliation math.
- 24-hour withdrawal limits.
- Insufficient funds behavior.
- Failed withdrawal recovery.
- Worker batching and duplicate recovery protection.
- Wallet audit pass/fail cases.
- API success and structured error responses.
- Concurrent withdrawal requests to protect against double-spend.

SQLite is used for fast isolated local tests. PostgreSQL-specific lock semantics are represented in code and should be covered by a future PostgreSQL-backed CI suite for exact `NOWAIT` and `SKIP LOCKED` behavior.

## 8. Trade-Offs

This submission deliberately keeps several production concerns lightweight:

| Trade-off | Current Choice | Production Evolution |
| --- | --- | --- |
| Migrations | No Alembic yet; Docker demo can auto-create tables. | Add Alembic migration lifecycle and reviewable schema changes. |
| Workers | Synchronous functions and manual trigger endpoint. | Move to Celery/RQ or Kafka/RabbitMQ consumers. |
| Authentication | Out of scope. | Add auth, RBAC, admin-only reconciliation, and webhook signing. |
| External payouts | Simulated webhook. | Integrate payment gateway adapter with retries and signed callbacks. |
| Observability | Test and API feedback. | Add structured logs, metrics, traces, and alerting. |
| Pagination | Simple list endpoints. | Cursor pagination for sales and transactions. |

These choices keep the assignment runnable and reviewable while preserving a clean path to production hardening.

## 9. Scaling To 100,000+ Creators

To scale this system for a large creator marketplace:

- Use a dedicated queue for sale advance events and payout recovery events.
- Partition or shard the ledger by creator ID or time window as data volume grows.
- Add read replicas and materialized read models for dashboard/reporting traffic.
- Keep wallet mutation APIs pinned to the primary database.
- Add idempotency keys to all externally retried requests.
- Add an outbox table so committed financial events are published reliably.
- Add PostgreSQL lock wait metrics and alerting.
- Add rate limits and API-level abuse protection.
- Add gateway-specific reconciliation jobs for delayed settlement states.
- Move long-running jobs away from request/response paths.

The core principle remains unchanged: every financial state transition must be transactional, idempotent, auditable, and recoverable.

## 10. Operational Notes

`AUTO_CREATE_TABLES=true` exists only for Docker-based assignment review. It allows a fresh local Postgres volume to run the dashboard immediately.

For production:

1. Set `AUTO_CREATE_TABLES=false`.
2. Add Alembic migrations.
3. Run migrations as a deployment step.
4. Restrict manual worker trigger endpoints behind admin authentication.
5. Require signed webhook payloads from the payout provider.
6. Alert on wallet audit mismatches immediately.
