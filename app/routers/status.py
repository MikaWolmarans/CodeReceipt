from fastapi import APIRouter, HTTPException

from app.models.session import StatusResponse
from app.services.session import session_service

router = APIRouter()


@router.get('/status/{session_id}', response_model=StatusResponse)
async def status(session_id: str) -> StatusResponse:
    session = await session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    return StatusResponse(
        session_id=session_id,
        status=session.get('status', 'pending'),
        progress=session.get('progress', 0),
        error=session.get('error'),
    )
