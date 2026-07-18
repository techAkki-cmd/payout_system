from fastapi import APIRouter

from app.api.v1.endpoints import (
    audit,
    payouts,
    reconciliation,
    sales,
    transactions,
    users,
    webhooks,
    withdrawals,
)

# Versioned routing keeps future payout endpoints grouped behind one stable prefix.
api_router: APIRouter = APIRouter()

api_router.include_router(sales.router, prefix="/sales", tags=["Sales"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["Transactions"])
api_router.include_router(audit.router, prefix="/audit", tags=["Audit"])
api_router.include_router(
    reconciliation.router,
    prefix="/reconciliation",
    tags=["Reconciliation"],
)
api_router.include_router(payouts.router, prefix="/payouts", tags=["Payouts"])
api_router.include_router(withdrawals.router, prefix="/withdrawals", tags=["Withdrawals"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
