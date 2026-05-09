"""GET /preview/{session_id} — public free-tier data for the teaser panel."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.session import session_service

logger = logging.getLogger(__name__)
router = APIRouter()

_QUICK_START_PREVIEW_CHARS = 220


class SectionCounts(BaseModel):
    risks: int = 0
    files: int = 0
    systems: int = 0
    env_vars: int = 0
    services: int = 0


class PreviewResponse(BaseModel):
    session_id: str
    status: str
    repo_name: str
    app_type: str
    stack_summary: str
    file_count: int
    confidence: str
    section_counts: SectionCounts
    quick_start_preview: str
    paid: bool
    payment_email: str | None


@router.get('/preview/{session_id}', response_model=PreviewResponse)
async def get_preview(session_id: str) -> PreviewResponse:
    session = await session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')

    status = session.get('status', 'pending')
    analysis = session.get('analysis', {}) or {}
    synthesis = analysis.get('synthesis', {}) or {}
    stack = session.get('stack', {}) or {}

    repo_name = analysis.get('repo_name', 'repository')
    app_type = synthesis.get('app_type', '') or stack.get('primary_language', 'Unknown')
    confidence = synthesis.get('analysis_confidence', 'medium')

    # Stack summary: primary language + top frameworks
    languages = stack.get('languages', []) or []
    frameworks = stack.get('frameworks', []) or []
    stack_parts = languages[:2] + frameworks[:3]
    stack_summary = ', '.join(stack_parts) if stack_parts else 'Unknown'

    # File count from chunks
    chunks = analysis.get('chunks', []) or []
    file_count = len(chunks)

    # Quick start preview
    quick_start_raw = synthesis.get('owner_quick_start', '') or ''
    if isinstance(quick_start_raw, list):
        quick_start_raw = ' '.join(str(s) for s in quick_start_raw)
    quick_start_preview = quick_start_raw[:_QUICK_START_PREVIEW_CHARS]
    if len(quick_start_raw) > _QUICK_START_PREVIEW_CHARS:
        quick_start_preview += '…'

    # Section counts — real numbers from synthesis fields for teaser authenticity
    risks = _count_list(synthesis.get('risk_register')) + _count_list(synthesis.get('warning_lights'))
    systems = _count_list(synthesis.get('key_systems'))
    env_vars = _count_list(synthesis.get('environment_variables'))
    services = _count_list(synthesis.get('running_costs'))

    return PreviewResponse(
        session_id=session_id,
        status=status,
        repo_name=repo_name,
        app_type=str(app_type),
        stack_summary=stack_summary,
        file_count=file_count,
        confidence=str(confidence),
        section_counts=SectionCounts(
            risks=risks,
            files=file_count,
            systems=systems,
            env_vars=env_vars,
            services=services,
        ),
        quick_start_preview=quick_start_preview,
        paid=bool(session.get('paid', False)),
        payment_email=session.get('payment_email'),
    )


def _count_list(val) -> int:
    """Return len(val) if it's a list, else 0."""
    if isinstance(val, list):
        return len(val)
    return 0
