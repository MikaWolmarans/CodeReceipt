"""POST /webhooks/stripe — handles Stripe payment events."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services.agent_context import build_agent_context
from app.services.analysis.stack_detect import detect_stack
from app.services.analysis.synthesiser import analyse_repository, upgrade_synthesis_to_paid
from app.services.email import send_paid_manual_email
from app.services.ingestion.github import ingest_repo_url
from app.services.ingestion.zip_handler import ingest_zip_bytes
from app.services.pdf.builder import PdfRenderError, build_pdf_bytes
from app.services.session import session_service
from app.services.stripe_service import verify_webhook

logger = logging.getLogger(__name__)
router = APIRouter()


def _as_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware UTC (Mongo stores naive datetimes)."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


@router.post('/webhooks/stripe')
async def stripe_webhook(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    settings = get_settings()

    if not settings.stripe_webhook_secret:
        logger.warning('STRIPE_WEBHOOK_SECRET not set — webhook rejected')
        raise HTTPException(status_code=400, detail='Webhook not configured.')

    payload = await request.body()
    sig_header = request.headers.get('stripe-signature', '')

    try:
        event = verify_webhook(payload, sig_header, settings.stripe_webhook_secret)
    except Exception as exc:
        logger.warning('Stripe webhook signature invalid: %s', exc)
        raise HTTPException(status_code=400, detail='Invalid webhook signature.')

    if event['type'] == 'checkout.session.completed':
        stripe_session = event['data']['object']
        cr_session_id: str | None = stripe_session.get('metadata', {}).get('session_id')
        customer_email: str | None = stripe_session.get('customer_details', {}).get('email')
        stripe_checkout_id: str | None = stripe_session.get('id')

        if not cr_session_id:
            logger.error(
                'Stripe webhook missing session_id in metadata (checkout: %s)',
                stripe_checkout_id,
            )
            return JSONResponse({'ok': False})

        session = await session_service.get_session(cr_session_id)
        if not session:
            logger.error('Webhook: CodeReceipt session %s not found', cr_session_id)
            return JSONResponse({'ok': False})

        fulfillment = session.get('fulfillment_status', 'none')

        if fulfillment == 'complete':
            logger.info('Webhook replay for fulfilled session %s', cr_session_id)
            return JSONResponse({'ok': True})

        started_at = session.get('fulfillment_started_at')
        if fulfillment == 'processing' and started_at is not None:
            age = datetime.now(timezone.utc) - _as_utc(started_at)
            if age < timedelta(minutes=15):
                logger.info('Webhook replay while fulfillment in flight for %s', cr_session_id)
                return JSONResponse({'ok': True})
            logger.warning(
                'Stale fulfillment (%.0fs) for %s — restarting', age.total_seconds(), cr_session_id
            )

        # Record payment and claim fulfillment atomically, then respond immediately.
        await session_service.update_session(
            cr_session_id,
            paid=True,
            paid_at=datetime.now(timezone.utc),
            payment_email=customer_email,
            stripe_checkout_id=stripe_checkout_id,
            tier='owner_manual',
            fulfillment_status='processing',
            fulfillment_started_at=datetime.now(timezone.utc),
            fulfillment_error=None,
        )
        background_tasks.add_task(_fulfill_order, cr_session_id, customer_email)

    return JSONResponse({'ok': True})


async def _run_paid_analysis(session_id: str, session: dict) -> dict:
    """Full re-ingestion + paid-tier analysis. Returns the refreshed session."""
    settings = get_settings()
    source_meta = session.get('source_meta', {}) or {}

    if session.get('source_type') == 'github' and source_meta.get('url'):
        files, _meta = await ingest_repo_url(source_meta['url'], settings.max_github_repo_size_mb)
        repo_name = source_meta['url'].rstrip('/').split('/')[-1]
    else:
        zip_data = await session_service.get_upload(session_id)
        if not zip_data:
            raise RuntimeError('Stored upload missing for paid analysis.')
        files, _total = await ingest_zip_bytes(zip_data, settings.max_zip_size_mb)
        repo_name = (source_meta.get('filename') or 'uploaded-repo').removesuffix('.zip')

    files = files[: settings.paid_tier_max_files]
    stack = detect_stack(files)
    chunks, synthesis = await analyse_repository(files, stack, session.get('options', {}), tier='owner_manual')
    chunk_summaries_text = '\n\n'.join(c['summary'] for c in chunks)
    await session_service.update_session(
        session_id,
        analysis={'chunks': chunks, 'synthesis': synthesis, 'repo_name': repo_name},
        stack=stack,
        status='complete',
        progress=100,
        chunk_summaries_text=chunk_summaries_text,
        truncated=False,
    )
    await session_service.delete_upload(session_id)
    return await session_service.get_session(session_id)


async def _fulfill_order(session_id: str, customer_email: str | None) -> None:
    session = await session_service.get_session(session_id)
    if not session:
        logger.error('Fulfillment: session %s vanished', session_id)
        return
    try:
        # 1a. Full paid re-analysis for over-limit or truncated repos
        needs_full_analysis = (
            session.get('status') == 'awaiting_payment' or session.get('truncated', False)
        )
        if needs_full_analysis:
            logger.info('Running full paid analysis for %s', session_id)
            session = await _run_paid_analysis(session_id, session)
        # 1b. Upgrade synthesis using stored chunk summaries (non-fatal on failure)
        elif session.get('chunk_summaries_text'):
            try:
                full_synthesis = await upgrade_synthesis_to_paid(
                    session['chunk_summaries_text'], session.get('stack', {}), session.get('options', {})
                )
                updated_analysis = dict(session.get('analysis', {}))
                updated_analysis['synthesis'] = full_synthesis
                await session_service.update_session(session_id, analysis=updated_analysis)
                session = await session_service.get_session(session_id)
            except Exception as exc:
                logger.error('Synthesis upgrade failed for %s: %s', session_id, exc)
        else:
            logger.warning('No chunk_summaries_text for %s — PDF uses free synthesis', session_id)

        # 2. Generate + store PDF and agent context (fatal on failure — session remains
        #    'processing' until Stripe re-delivers; /export regenerates on-demand)
        repo_name = session.get('analysis', {}).get('repo_name', 'repository')
        pdf_bytes = await build_pdf_bytes(session)
        await session_service.store_pdf(session_id, pdf_bytes, repo_name)
        await session_service.store_agent_context(session_id, build_agent_context(session))
        await session_service.update_session(session_id, pdf_delivered=True)

        # 3. Record customer + send email (non-fatal — PDF is stored, /export works)
        if customer_email:
            try:
                await session_service.record_customer(customer_email, session_id)
            except Exception as exc:
                logger.warning('Customer record failed for %s: %s', session_id, exc)
            try:
                agent_md = await session_service.get_agent_context(session_id)
                await send_paid_manual_email(customer_email, session_id, repo_name, pdf_bytes,
                                             agent_context=agent_md)
            except Exception as exc:
                logger.error('Email delivery failed for %s: %s', session_id, exc)

        await session_service.update_session(session_id, fulfillment_status='complete')
        logger.info('Fulfillment complete for %s', session_id)

    except Exception as exc:
        logger.error('Fulfillment FAILED for %s: %s', session_id, exc, exc_info=True)
        await session_service.update_session(
            session_id,
            fulfillment_status='failed',
            fulfillment_error=str(exc) or 'fulfillment failed',
        )
