from io import BytesIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services.pdf.builder import build_pdf_bytes
from app.services.session import session_service

router = APIRouter()


@router.get('/export/{session_id}')
async def export_pdf(session_id: str):
    session = await session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    if session.get('status') != 'complete':
        raise HTTPException(status_code=409, detail='Analysis is not complete yet.')

    repo_name = session.get('analysis', {}).get('repo_name', 'repository')
    pdf_bytes = await build_pdf_bytes(session)
    await session_service.update_session(session_id, pdf_delivered=True)

    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{repo_name}-manual.pdf"'},
    )
