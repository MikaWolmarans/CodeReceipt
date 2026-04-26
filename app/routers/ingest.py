import json
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

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


async def _run_analysis(session_id: str, files, repo_name: str) -> None:
    session = await session_service.get_session(session_id)
    if not session:
        return
    try:
        await session_service.update_session(session_id, status='processing', progress=25)
        stack = detect_stack(files)
        await session_service.update_session(session_id, stack=stack, progress=45)
        chunks, synthesis = await analyse_repository(files, stack, session.get('options', {}))
        await session_service.update_session(
            session_id,
            analysis={'chunks': chunks, 'synthesis': synthesis, 'repo_name': repo_name},
            status='complete',
            progress=100,
        )
        notify_email = session.get('notify_email')
        if notify_email:
            await send_manual_ready_email(notify_email, session_id, repo_name)
    except Exception:
        await session_service.update_session(session_id, status='failed', error='Analysis failed unexpectedly.')


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

    if session_id:
        existing = await session_service.get_session(session_id)
        if not existing:
            raise HTTPException(status_code=404, detail='Session not found.')
        return AnalyseResponse(session_id=session_id)

    if bool(url) == bool(zip_file):
        raise HTTPException(status_code=400, detail='Provide either a repository URL or a ZIP file.')

    await enforce_daily_limit()

    options = AnalysisOptions()
    if options_json:
        try:
            options = AnalysisOptions(**json.loads(options_json))
        except Exception as exc:
            raise HTTPException(status_code=400, detail='Invalid options payload.') from exc

    try:
        if url:
            files, source_meta = await ingest_repo_url(url, settings.max_github_repo_size_mb)
            source_type = 'github'
            repo_name = source_meta.get('url', 'repository').rstrip('/').split('/')[-1]
            source_meta['filename'] = None
        else:
            data = await zip_file.read()
            files, total_bytes = await ingest_zip_bytes(data, settings.max_zip_size_mb)
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
        raise HTTPException(status_code=400, detail='No supported text files found for analysis.')

    session = SessionDocument(source_type=source_type, source_meta=source_meta, options=options, notify_email=email)
    new_session_id = await session_service.create_session(session)

    background_tasks.add_task(_run_analysis, new_session_id, files, repo_name)
    return AnalyseResponse(session_id=new_session_id)
