from fastapi import APIRouter

# Versioned routing keeps future payout endpoints grouped behind one stable prefix.
api_router: APIRouter = APIRouter()
