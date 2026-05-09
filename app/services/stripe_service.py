"""Stripe integration — checkout session creation and webhook verification."""
from __future__ import annotations

import logging

import stripe

from app.config import get_settings

logger = logging.getLogger(__name__)


def _client() -> stripe.StripeClient:
    settings = get_settings()
    return stripe.StripeClient(settings.stripe_secret_key or '')


async def create_checkout_session(
    session_id: str,
    repo_name: str,
    prefill_email: str | None,
    frontend_url: str,
    price_id: str,
) -> str:
    """Create a Stripe Checkout session and return its URL."""
    params: dict = {
        'mode': 'payment',
        'line_items': [{'price': price_id, 'quantity': 1}],
        'success_url': f'{frontend_url}?payment=success&session_id={session_id}',
        'cancel_url': f'{frontend_url}?payment=cancelled&session_id={session_id}',
        'metadata': {'session_id': session_id, 'repo_name': repo_name},
        'payment_intent_data': {'metadata': {'session_id': session_id}},
        'allow_promotion_codes': True,  # "Have a promo code?" field in checkout
    }
    if prefill_email:
        params['customer_email'] = prefill_email

    client = _client()
    checkout = client.checkout.sessions.create(params)
    return checkout.url


def verify_webhook(payload: bytes, sig_header: str, webhook_secret: str) -> dict:
    """Verify Stripe webhook signature and return the parsed event dict."""
    return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
