"""POST /checkout/{session_id} — creates a Stripe Checkout session."""
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import get_settings
from app.services.session import session_service
from app.services.stripe_service import create_checkout_session

logger = logging.getLogger(__name__)
router = APIRouter()


class CheckoutResponse(BaseModel):
    checkout_url: str


@router.post('/checkout/{session_id}', response_model=CheckoutResponse)
async def create_checkout(session_id: str) -> CheckoutResponse:
    settings = get_settings()

    if not settings.stripe_secret_key or not settings.stripe_price_id:
        raise HTTPException(status_code=503, detail='Payments are not configured.')

    session = await session_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found.')
    if session.get('status') != 'complete':
        raise HTTPException(status_code=409, detail='Analysis must complete before payment.')
    if session.get('paid'):
        raise HTTPException(status_code=409, detail='This session has already been paid.')

    repo_name = session.get('analysis', {}).get('repo_name', 'repository')
    prefill_email = session.get('notify_email') or session.get('payment_email')

    try:
        url = await create_checkout_session(
            session_id=session_id,
            repo_name=repo_name,
            prefill_email=prefill_email,
            frontend_url=settings.frontend_url,
            price_id=settings.stripe_price_id,
        )
    except Exception as exc:
        logger.error('Stripe checkout creation failed for %s: %s', session_id, exc)
        raise HTTPException(status_code=502, detail='Could not create checkout session.') from exc

    return CheckoutResponse(checkout_url=url)
