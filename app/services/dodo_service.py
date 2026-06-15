"""Dodo Payments integration — checkout session creation and webhook verification."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging

import httpx

logger = logging.getLogger(__name__)

_TEST_BASE = 'https://test.dodopayments.com'
_LIVE_BASE = 'https://live.dodopayments.com'


def _base(test_mode: bool) -> str:
    return _TEST_BASE if test_mode else _LIVE_BASE


async def create_checkout_session(
    session_id: str,
    repo_name: str,
    prefill_email: str | None,
    frontend_url: str,
    product_id: str,
    api_key: str,
    test_mode: bool = True,
    amount_cents: int | None = None,
) -> str:
    """Create a Dodo Payments checkout session and return its URL.

    *amount_cents* sets the pay-what-you-want price (in the currency's lowest
    unit) on the cart line. It is only honoured for PWYW-enabled products and
    must fall within the product's configured min/max; omit it to let Dodo's
    own checkout prompt the buyer for an amount.
    """
    cart_item: dict = {'product_id': product_id, 'quantity': 1}
    if amount_cents is not None:
        cart_item['amount'] = amount_cents
    payload: dict = {
        'product_cart': [cart_item],
        'return_url': f'{frontend_url}?payment=success&session_id={session_id}',
        'cancel_url': f'{frontend_url}?payment=cancelled&session_id={session_id}',
        'metadata': {'session_id': session_id, 'repo_name': repo_name},
        'customization': {'theme': 'dark'},
        'feature_flags': {'allow_discount_code': True},
    }
    if prefill_email:
        payload['customer'] = {'email': prefill_email}

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f'{_base(test_mode)}/checkouts',
            json=payload,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
        )
        r.raise_for_status()

    data = r.json()
    checkout_url: str = data['checkout_url']
    logger.info('Dodo checkout session created for %s: %s', session_id, checkout_url)
    return checkout_url


def verify_webhook(payload: bytes, headers: dict, webhook_secret: str) -> dict:
    """Verify a Standard Webhooks signature and return the parsed event.

    Dodo follows the Standard Webhooks spec:
    - signed message = "{webhook-id}.{webhook-timestamp}.{raw_body}"
    - key = base64.b64decode(webhook_secret)
    - signature = base64.b64encode(hmac_sha256(key, message))
    - header = "v1,{signature}" (space-separated if multiple)
    """
    msg_id = headers.get('webhook-id', '')
    timestamp = headers.get('webhook-timestamp', '')
    sig_header = headers.get('webhook-signature', '')

    if not sig_header:
        raise ValueError('Missing webhook-signature header')

    signed_content = f'{msg_id}.{timestamp}.{payload.decode("utf-8")}'

    try:
        secret_bytes = base64.b64decode(webhook_secret)
    except Exception:
        secret_bytes = webhook_secret.encode('utf-8')

    expected = base64.b64encode(
        hmac.new(secret_bytes, signed_content.encode('utf-8'), hashlib.sha256).digest()
    ).decode('ascii')

    for part in sig_header.split(' '):
        scheme, _, sig = part.partition(',')
        if scheme == 'v1' and hmac.compare_digest(sig, expected):
            return json.loads(payload)

    raise ValueError('Webhook signature verification failed')
