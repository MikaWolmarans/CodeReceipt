"""POST /checkout/{session_id} — creates a Dodo Payments checkout session."""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.services.dodo_service import create_checkout_session
from app.services.session import session_service

logger = logging.getLogger(__name__)
router = APIRouter()


class CheckoutRequest(BaseModel):
    # Pay-what-you-want amount in the currency's lowest unit (cents).
    # Optional: when omitted, Dodo's checkout prompts the buyer for an amount.
    amount_cents: Optional[int] = None


class CheckoutResponse(BaseModel):
    checkout_url: str
    test_mode: bool


@router.post('/checkout/{session_id}', response_model=CheckoutResponse)
async def create_checkout(
    session_id: str, body: Optional[CheckoutRequest] = None
) -> CheckoutResponse:
    settings = get_settings()

    if not settings.dodo_api_key or not settings.dodo_product_id:
        raise HTTPException(status_code=503, detail='Payments are not configured.')

    amount_cents = body.amount_cents if body else None
    if amount_cents is not None:
        if amount_cents < settings.dodo_pwyw_min_cents:
            raise HTTPException(
                status_code=422,
                detail=f'Minimum is {settings.dodo_pwyw_min_cents / 100:.2f}.',
            )
        if amount_cents > settings.dodo_pwyw_max_cents:
            raise HTTPException(
                status_code=422,
                detail=f'Maximum is {settings.dodo_pwyw_max_cents / 100:.2f}.',
            )

    session = await session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    if session.get('status') not in {'complete', 'awaiting_payment'}:
        raise HTTPException(status_code=409, detail='Analysis must complete before payment.')
    if session.get('paid'):
        raise HTTPException(status_code=409, detail='This session has already been paid.')

    repo_name = (
        session.get('analysis', {}).get('repo_name')
        or (
            (session.get('source_meta', {}).get('url') or session.get('source_meta', {}).get('filename') or 'repository')
            .rstrip('/')
            .split('/')[-1]
            .removesuffix('.zip')
        )
    )
    prefill_email = session.get('notify_email') or session.get('payment_email')

    try:
        url = await create_checkout_session(
            session_id=session_id,
            repo_name=repo_name,
            prefill_email=prefill_email,
            frontend_url=settings.frontend_url,
            product_id=settings.dodo_product_id,
            api_key=settings.dodo_api_key,
            test_mode=settings.dodo_test_mode,
            amount_cents=amount_cents,
        )
    except Exception as exc:
        logger.error('Dodo checkout creation failed for %s: %s', session_id, exc)
        raise HTTPException(status_code=502, detail='Could not create checkout session.') from exc

    return CheckoutResponse(checkout_url=url, test_mode=settings.dodo_test_mode)
