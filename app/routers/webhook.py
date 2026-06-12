"""POST /webhooks/stripe — handles Stripe payment events."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services.analysis.synthesiser import upgrade_synthesis_to_paid
from app.services.email import send_paid_manual_email
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


async def _fulfill_order(session_id: str, customer_email: str | None) -> None:
    session = await session_service.get_session(session_id)
    if not session:
        logger.error('Fulfillment: session %s vanished', session_id)
        return
    try:
        # 1. Upgrade synthesis using stored chunk summaries (non-fatal on failure)
        chunk_summaries_text = session.get('chunk_summaries_text', '')
        if chunk_summaries_text:
            try:
                full_synthesis = await upgrade_synthesis_to_paid(
                    chunk_summaries_text, session.get('stack', {}), session.get('options', {})
                )
                updated_analysis = dict(session.get('analysis', {}))
                updated_analysis['synthesis'] = full_synthesis
                await session_service.update_session(session_id, analysis=updated_analysis)
                session = await session_service.get_session(session_id)
            except Exception as exc:
                logger.error('Synthesis upgrade failed for %s: %s', session_id, exc)
        else:
            logger.warning('No chunk_summaries_text for %s — PDF uses free synthesis', session_id)

        # 2. Generate + store PDF (fatal on failure — session remains 'processing'
        #    until Stripe re-delivers; /export regenerates on-demand for paid sessions)
        repo_name = session.get('analysis', {}).get('repo_name', 'repository')
        pdf_bytes = await build_pdf_bytes(session)
        await session_service.store_pdf(session_id, pdf_bytes, repo_name)
        await session_service.update_session(session_id, pdf_delivered=True)

        # 3. Record customer + send email (non-fatal — PDF is stored, /export works)
        if customer_email:
            try:
                await session_service.record_customer(customer_email, session_id)
            except Exception as exc:
                logger.warning('Customer record failed for %s: %s', session_id, exc)
            try:
                await send_paid_manual_email(customer_email, session_id, repo_name, pdf_bytes)
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
