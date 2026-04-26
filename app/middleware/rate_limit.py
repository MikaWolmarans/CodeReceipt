from fastapi import HTTPException

from app.services.session import session_service


async def enforce_daily_limit() -> None:
    allowed = await session_service.increment_daily_cap_or_reject()
    if not allowed:
        raise HTTPException(status_code=429, detail='Daily analysis cap reached. Please try again tomorrow.')
