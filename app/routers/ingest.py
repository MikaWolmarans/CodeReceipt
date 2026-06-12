from __future__ import annotations

import hashlib
import json
import logging
import traceback
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

logger = logging.getLogger(__name__)

from app.config import get_settings
from app.middleware.rate_limit import enforce_daily_limit
from app.models.session import AnalyseResponse, AnalysisOptions, SessionDocument
from app.services.analysis.stack_detect import detect_stack
from app.services.analysis.synthesiser import analyse_repository
from app.services.email import send_manual_ready_email
from app.services.ingestion.github import RepoIngestionError, ingest_repo_url
from app.services.ingestion.zip_handler import ZipValidationError, ingest_zip_bytes
from app.services.session import session_service

router = APIRouter()


def _compute_repo_hash(url: str | None, commit_sha: str | None, zip_data: bytes | None) -> str:
    """Stable cache key for a given repo + commit or ZIP content."""
    h = hashlib.sha256()
    if url:
        h.update(url.encode())
    if commit_sha:
        h.update(commit_sha.encode())
    if zip_data:
        h.update(zip_data)
    return h.hexdigest()


async def _run_analysis(session_id: str, files, repo_name: str) -> None:
    session = await session_service.get_session(session_id)
    if not session:
        return
    tier = session.get('tier', 'free')
    try:
        await session_service.update_session(session_id, status='processing', progress=25)
        stack = detect_stack(files)
        await session_service.update_session(session_id, stack=stack, progress=45)
        chunks, synthesis = await analyse_repository(
            files, stack, session.get('options', {}), tier=tier
        )

        # Store joined chunk summaries for potential paid upgrade (avoid re-running chunks)
        chunk_summaries_text = '\n\n'.join(c['summary'] for c in chunks)

        await session_service.update_session(
            session_id,
            analysis={'chunks': chunks, 'synthesis': synthesis, 'repo_name': repo_name},
            status='complete',
            progress=100,
            chunk_summaries_text=chunk_summaries_text,
        )
        notify_email = session.get('notify_email')
        if notify_email:
            await send_manual_ready_email(notify_email, session_id, repo_name)
    except Exception as exc:
        logger.error(
            'Analysis failed for session %s: %s\n%s', session_id, exc, traceback.format_exc()
        )
        await session_service.update_session(
            session_id, status='failed', error=str(exc) or 'Analysis failed unexpectedly.'
        )


@router.post('/analyse', response_model=AnalyseResponse)
async def analyse(
    background_tasks: BackgroundTasks,
    url: Annotated[str | None, Form()] = None,
    zip_file: UploadFile | None = File(default=None),
    options_json: Annotated[str | None, Form()] = None,
    session_id: Annotated[str | None, Form()] = None,
    email: Annotated[str | None, Form()] = None,
) -> AnalyseResponse:
    settings = get_settings()

    if settings.maintenance_mode:
        raise HTTPException(
            status_code=503,
            detail='Service is temporarily unavailable for maintenance. Please check back soon.',
        )

    if session_id:
        existing = await session_service.get_session(session_id)
        if not existing:
            raise HTTPException(status_code=404, detail='Session not found.')
        return AnalyseResponse(session_id=session_id)

    if bool(url) == bool(zip_file):
        raise HTTPException(
            status_code=400, detail='Provide either a repository URL or a ZIP file.'
        )

    await enforce_daily_limit()

    options = AnalysisOptions()
    if options_json:
        try:
            options = AnalysisOptions(**json.loads(options_json))
        except Exception as exc:
            raise HTTPException(status_code=400, detail='Invalid options payload.') from exc

    try:
        zip_data: bytes | None = None
        commit_sha: str | None = None

        if url:
            files, source_meta = await ingest_repo_url(url, settings.max_github_repo_size_mb)
            source_type = 'github'
            repo_name = source_meta.get('url', 'repository').rstrip('/').split('/')[-1]
            source_meta['filename'] = None
            commit_sha = source_meta.get('commit_sha')  # ingestion may provide this
            total_bytes = source_meta.get('total_bytes', 0)
        else:
            zip_data = await zip_file.read()
            files, total_bytes = await ingest_zip_bytes(zip_data, settings.max_zip_size_mb)
            source_type = 'zip'
            source_meta = {
                'url': None,
                'filename': zip_file.filename,
                'file_count': len(files),
                'total_bytes': total_bytes,
            }
            repo_name = (zip_file.filename or 'uploaded-repo').removesuffix('.zip')
    except (RepoIngestionError, ZipValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not files:
        raise HTTPException(
            status_code=400, detail='No supported text files found for analysis.'
        )

    # ── Free tier size gate ──────────────────────────────────────────────────
    repo_hash = _compute_repo_hash(url, commit_sha, zip_data)
    free_max_bytes = settings.free_tier_max_mb * 1024 * 1024
    if total_bytes > free_max_bytes:
        size_mb = round(total_bytes / (1024 * 1024), 1)
        session = SessionDocument(
            source_type=source_type,
            source_meta=source_meta,
            options=options,
            notify_email=email,
            tier='owner_manual',
            status='awaiting_payment',
            repo_hash=repo_hash,
            total_file_count=len(files),
        )
        new_session_id = await session_service.create_session(session)
        if zip_data is not None:
            await session_service.store_upload(new_session_id, zip_data)
            await session_service.update_session(new_session_id, upload_stored=True)
        return AnalyseResponse(
            session_id=new_session_id,
            requires_upgrade=True,
            upgrade_reason=(
                f'This repository is {size_mb} MB — over the {settings.free_tier_max_mb} MB free scan limit. '
                f'Get the Owner\'s Manual to run the full analysis.'
            ),
        )

    # ── Free tier file count gate ────────────────────────────────────────────
    total_file_count = len(files)
    truncated = total_file_count > settings.free_tier_max_files
    if truncated:
        files = files[: settings.free_tier_max_files]

    # ── Cache check ──────────────────────────────────────────────────────────
    cached = await session_service.find_cached_session(repo_hash, 'free')
    if cached:
        logger.info('Returning cached free session %s for hash %s', cached['_id'], repo_hash[:8])
        return AnalyseResponse(session_id=cached['_id'])

    # ── Free daily cap ───────────────────────────────────────────────────────
    free_allowed = await session_service.increment_free_daily_or_reject()
    if not free_allowed:
        raise HTTPException(
            status_code=429,
            detail='Daily free scan limit reached. Try again tomorrow, or purchase an Owner\'s Manual.',
        )

    session = SessionDocument(
        source_type=source_type,
        source_meta=source_meta,
        options=options,
        notify_email=email,
        tier='free',
        repo_hash=repo_hash,
        truncated=truncated,
        total_file_count=total_file_count,
    )
    new_session_id = await session_service.create_session(session)

    if truncated and zip_data is not None:
        await session_service.store_upload(new_session_id, zip_data)
        await session_service.update_session(new_session_id, upload_stored=True)

    background_tasks.add_task(_run_analysis, new_session_id, files, repo_name)
    return AnalyseResponse(session_id=new_session_id)
