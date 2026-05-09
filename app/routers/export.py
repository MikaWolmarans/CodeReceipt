import logging
import traceback
from io import BytesIO

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.services.pdf.builder import PdfRenderError, build_pdf_bytes
from app.services.session import session_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get('/export/{session_id}')
async def export_pdf(session_id: str):
    session = await session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    if session.get('status') != 'complete':
        raise HTTPException(status_code=409, detail='Analysis is not complete yet.')

    # Payment gate — only paid sessions may export the full PDF
    if not session.get('paid', False):
        raise HTTPException(
            status_code=402,
            detail={
                'message': 'Payment required to download the full Owner\'s Manual.',
                'checkout_path': f'/checkout/{session_id}',
            },
        )

    repo_name = session.get('analysis', {}).get('repo_name', 'repository')

    # Serve stored PDF from pdf_store (generated on payment); fallback to live render
    pdf_bytes = await session_service.get_pdf(session_id)

    if not pdf_bytes:
        logger.warning('PDF not found in store for %s — rendering on-demand', session_id)
        try:
            pdf_bytes = await build_pdf_bytes(session)
            await session_service.store_pdf(session_id, pdf_bytes, repo_name)
        except PdfRenderError as exc:
            logger.error('PDF render error: %s', exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f'PDF rendering failed: {exc}')
        except Exception as exc:
            logger.error('Unexpected error during PDF export: %s', exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f'Unexpected error: {traceback.format_exc()}')

    await session_service.update_session(session_id, pdf_delivered=True)

    safe_name = repo_name.replace('"', '').replace('/', '-')
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="{safe_name}-owners-manual.pdf"'},
    )
