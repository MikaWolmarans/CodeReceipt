"""Tests for POST /webhooks/stripe — signature gate and fulfillment."""
import pytest
from app.services.session import session_service
from app.services.pdf.builder import PdfRenderError


def _event(session_id='s1', email='buyer@example.com'):
    return {
        'type': 'checkout.session.completed',
        'data': {'object': {
            'id': 'cs_test_123',
            'metadata': {'session_id': session_id},
            'customer_details': {'email': email},
        }},
    }


@pytest.mark.asyncio
async def test_webhook_no_secret_400(api):
    r = await api.post('/webhooks/stripe', content=b'{}', headers={'stripe-signature': 'x'})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_webhook_bad_signature_400(api, monkeypatch):
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_dummy')

    def _raise(payload, sig, secret):
        raise ValueError('bad sig')

    monkeypatch.setattr('app.routers.webhook.verify_webhook', _raise)
    r = await api.post('/webhooks/stripe', content=b'{}', headers={'stripe-signature': 'x'})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_webhook_already_paid_idempotent(api, mock_db, monkeypatch):
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_dummy')
    await mock_db['sessions'].insert_one({'_id': 's1', 'status': 'complete', 'paid': True})

    monkeypatch.setattr('app.routers.webhook.verify_webhook', lambda *a: _event('s1'))
    patched = {'called': False}

    async def _no_call(*a, **kw):
        patched['called'] = True

    monkeypatch.setattr('app.routers.webhook.build_pdf_bytes', _no_call)
    monkeypatch.setattr('app.routers.webhook.send_paid_manual_email', _no_call)
    monkeypatch.setattr('app.routers.webhook.upgrade_synthesis_to_paid', _no_call)

    r = await api.post('/webhooks/stripe', content=b'{}', headers={'stripe-signature': 'x'})
    assert r.status_code == 200
    assert r.json() == {'ok': True}
    assert not patched['called'], 'Fulfillment should not run for already-paid session'


@pytest.mark.asyncio
async def test_webhook_happy_path(api, mock_db, monkeypatch):
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_dummy')
    await mock_db['sessions'].insert_one({
        '_id': 's2',
        'status': 'complete',
        'paid': False,
        'chunk_summaries_text': 'chunk data',
        'stack': {},
        'options': {},
        'analysis': {'repo_name': 'my-repo', 'synthesis': {}},
    })

    monkeypatch.setattr('app.routers.webhook.verify_webhook', lambda *a: _event('s2'))

    async def _upgrade(chunk_summaries_text, stack, options):
        return {'what_you_built': 'x'}

    async def _build_pdf(session):
        return b'%PDF-paid'

    async def _send_email(*a, **kw):
        pass

    monkeypatch.setattr('app.routers.webhook.upgrade_synthesis_to_paid', _upgrade)
    monkeypatch.setattr('app.routers.webhook.build_pdf_bytes', _build_pdf)
    monkeypatch.setattr('app.routers.webhook.send_paid_manual_email', _send_email)

    r = await api.post('/webhooks/stripe', content=b'{}', headers={'stripe-signature': 'x'})
    assert r.status_code == 200

    session = await session_service.get_session('s2')
    assert session['paid'] is True
    pdf = await session_service.get_pdf('s2')
    assert pdf == b'%PDF-paid'

    customers = await mock_db['customers'].find({'email': 'buyer@example.com'}).to_list(None)
    assert len(customers) == 1


@pytest.mark.asyncio
async def test_webhook_pdf_failure_500(api, mock_db, monkeypatch):
    # NOTE: session is marked paid before PDF render — Stripe retries will short-circuit.
    # Known limitation; addressed by plans/004.
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_dummy')
    await mock_db['sessions'].insert_one({
        '_id': 's3',
        'status': 'complete',
        'paid': False,
        'chunk_summaries_text': '',
        'stack': {},
        'options': {},
        'analysis': {'repo_name': 'fail-repo', 'synthesis': {}},
    })

    monkeypatch.setattr('app.routers.webhook.verify_webhook', lambda *a: _event('s3'))

    async def _bad_pdf(session):
        raise PdfRenderError('boom')

    monkeypatch.setattr('app.routers.webhook.build_pdf_bytes', _bad_pdf)

    r = await api.post('/webhooks/stripe', content=b'{}', headers={'stripe-signature': 'x'})
    assert r.status_code == 500
