"""POST /webhooks/stripe — handles Stripe payment events."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services.analysis.synthesiser import upgrade_synthesis_to_paid
from app.services.email import send_paid_manual_email
from app.services.pdf.builder import PdfRenderError, build_pdf_bytes
from app.services.session import session_service
from app.services.stripe_service import verify_webhook

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post('/webhooks/stripe')
async def stripe_webhook(request: Request) -> JSONResponse:
    settings = get_settings()

    if not settings.stripe_webhook_secret:
        logger.warning('STRIPE_WEBHOOK_SECRET not set — webhook rejected')
        raise HTTPException(status_code=400, detail='Webhook not configured.')

    payload = await request.body()  # raw bytes — required for signature verification
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

        # Idempotency — safe to replay
        if session.get('paid'):
            logger.info('Webhook replay for already-paid session %s', cr_session_id)
            return JSONResponse({'ok': True})

        # 1. Mark session as paid
        await session_service.update_session(
            cr_session_id,
            paid=True,
            paid_at=datetime.now(timezone.utc),
            payment_email=customer_email,
            stripe_checkout_id=stripe_checkout_id,
            tier='owner_manual',
        )
        logger.info('Session %s marked paid (email: %s)', cr_session_id, customer_email)

        # 2. Upgrade synthesis from free → full (reuse stored chunk summaries)
        try:
            chunk_summaries_text = session.get('chunk_summaries_text', '')
            stack = session.get('stack', {})
            options = session.get('options', {})

            if chunk_summaries_text:
                full_synthesis = await upgrade_synthesis_to_paid(
                    chunk_summaries_text, stack, options
                )
                # Merge full synthesis into existing analysis
                updated_analysis = dict(session.get('analysis', {}))
                updated_analysis['synthesis'] = full_synthesis
                await session_service.update_session(cr_session_id, analysis=updated_analysis)
                # Refresh session for PDF generation
                session = await session_service.get_session(cr_session_id)
            else:
                logger.warning(
                    'No chunk_summaries_text for session %s — PDF will use free synthesis',
                    cr_session_id,
                )
        except Exception as exc:
            logger.error('Synthesis upgrade failed for %s: %s', cr_session_id, exc)
            # Non-fatal: continue with free synthesis for PDF

        # 3. Generate PDF
        repo_name = session.get('analysis', {}).get('repo_name', 'repository')
        try:
            pdf_bytes = await build_pdf_bytes(session)
            await session_service.store_pdf(cr_session_id, pdf_bytes, repo_name)
            await session_service.update_session(cr_session_id, pdf_delivered=True)
            logger.info('PDF generated and stored for session %s (%d bytes)', cr_session_id, len(pdf_bytes))
        except PdfRenderError as exc:
            logger.error('PDF render failed post-payment for %s: %s', cr_session_id, exc)
            # Return 500 → Stripe retries for up to 72 hours
            return JSONResponse({'ok': False, 'error': 'pdf_render_failed'}, status_code=500)
        except Exception as exc:
            logger.error('Unexpected PDF error for %s: %s', cr_session_id, exc)
            return JSONResponse({'ok': False, 'error': 'unexpected'}, status_code=500)

        # 4. Record customer email
        if customer_email:
            try:
                await session_service.record_customer(customer_email, cr_session_id)
            except Exception as exc:
                logger.warning('Customer record failed for %s: %s', cr_session_id, exc)

        # 5. Send email with PDF attached
        if customer_email:
            try:
                await send_paid_manual_email(
                    customer_email, cr_session_id, repo_name, pdf_bytes
                )
                logger.info('Paid email sent to %s for session %s', customer_email, cr_session_id)
            except Exception as exc:
                logger.error('Email delivery failed for %s: %s', cr_session_id, exc)
                # Non-fatal: PDF is stored, download link works even without email

    return JSONResponse({'ok': True})
