"""Tests for POST /webhooks/stripe — signature gate and fulfillment state machine."""
from datetime import datetime, timedelta, timezone

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


def _session(session_id, extra=None):
    doc = {
        '_id': session_id,
        'status': 'complete',
        'paid': False,
        'chunk_summaries_text': '',
        'stack': {},
        'options': {},
        'analysis': {'repo_name': 'my-repo', 'synthesis': {}},
    }
    if extra:
        doc.update(extra)
    return doc


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
async def test_webhook_fulfilled_idempotent(api, mock_db, monkeypatch):
    """Replay for a fully fulfilled session: fulfillment not re-run."""
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_dummy')
    await mock_db['sessions'].insert_one(
        _session('s1', {'paid': True, 'fulfillment_status': 'complete'})
    )
    monkeypatch.setattr('app.routers.webhook.verify_webhook', lambda *a: _event('s1'))

    called = {'n': 0}

    async def _no_call(*a, **kw):
        called['n'] += 1

    monkeypatch.setattr('app.routers.webhook.build_pdf_bytes', _no_call)
    monkeypatch.setattr('app.routers.webhook.send_paid_manual_email', _no_call)
    monkeypatch.setattr('app.routers.webhook.upgrade_synthesis_to_paid', _no_call)

    r = await api.post('/webhooks/stripe', content=b'{}', headers={'stripe-signature': 'x'})
    assert r.status_code == 200
    assert r.json() == {'ok': True}
    assert called['n'] == 0, 'Fulfillment must not run for completed session'


@pytest.mark.asyncio
async def test_webhook_in_flight_idempotent(api, mock_db, monkeypatch):
    """Replay while fulfillment is in-flight (recent started_at): not re-run."""
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_dummy')
    await mock_db['sessions'].insert_one(_session('s2', {
        'paid': True,
        'fulfillment_status': 'processing',
        'fulfillment_started_at': datetime.now(timezone.utc),
    }))
    monkeypatch.setattr('app.routers.webhook.verify_webhook', lambda *a: _event('s2'))

    called = {'n': 0}

    async def _no_call(*a, **kw):
        called['n'] += 1

    monkeypatch.setattr('app.routers.webhook.build_pdf_bytes', _no_call)

    r = await api.post('/webhooks/stripe', content=b'{}', headers={'stripe-signature': 'x'})
    assert r.status_code == 200
    assert called['n'] == 0, 'In-flight fulfillment must not be re-run'


@pytest.mark.asyncio
async def test_webhook_stale_processing_reruns(api, mock_db, monkeypatch):
    """Stale fulfillment_started_at (>15 min ago) triggers a re-run."""
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_dummy')
    await mock_db['sessions'].insert_one(_session('s3', {
        'fulfillment_status': 'processing',
        'fulfillment_started_at': datetime.now(timezone.utc) - timedelta(minutes=30),
    }))
    monkeypatch.setattr('app.routers.webhook.verify_webhook', lambda *a: _event('s3'))

    called = {'n': 0}

    async def _track_pdf(session):
        called['n'] += 1
        return b'%PDF-rerun'

    async def _noop(*a, **kw):
        pass

    monkeypatch.setattr('app.routers.webhook.build_pdf_bytes', _track_pdf)
    monkeypatch.setattr('app.routers.webhook.send_paid_manual_email', _noop)

    r = await api.post('/webhooks/stripe', content=b'{}', headers={'stripe-signature': 'x'})
    assert r.status_code == 200
    assert called['n'] == 1, 'Stale fulfillment must be restarted'


@pytest.mark.asyncio
async def test_webhook_happy_path(api, mock_db, monkeypatch):
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_dummy')
    await mock_db['sessions'].insert_one(_session('s4', {'chunk_summaries_text': 'chunk data'}))

    monkeypatch.setattr('app.routers.webhook.verify_webhook', lambda *a: _event('s4'))

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

    session = await session_service.get_session('s4')
    assert session['paid'] is True
    assert session['fulfillment_status'] == 'complete'

    pdf = await session_service.get_pdf('s4')
    assert pdf == b'%PDF-paid'

    customers = await mock_db['customers'].find({'email': 'buyer@example.com'}).to_list(None)
    assert len(customers) == 1


@pytest.mark.asyncio
async def test_webhook_pdf_failure_marks_failed(api, mock_db, monkeypatch):
    """PDF failure → 200 response (fast return), session marked failed, no pdf_store doc."""
    monkeypatch.setenv('STRIPE_WEBHOOK_SECRET', 'whsec_dummy')
    await mock_db['sessions'].insert_one(_session('s5'))

    monkeypatch.setattr('app.routers.webhook.verify_webhook', lambda *a: _event('s5'))

    async def _bad_pdf(session):
        raise PdfRenderError('boom')

    email_called = {'n': 0}

    async def _no_email(*a, **kw):
        email_called['n'] += 1

    monkeypatch.setattr('app.routers.webhook.build_pdf_bytes', _bad_pdf)
    monkeypatch.setattr('app.routers.webhook.send_paid_manual_email', _no_email)

    r = await api.post('/webhooks/stripe', content=b'{}', headers={'stripe-signature': 'x'})
    assert r.status_code == 200

    session = await session_service.get_session('s5')
    assert session['fulfillment_status'] == 'failed'
    assert 'boom' in session.get('fulfillment_error', '')

    pdf = await session_service.get_pdf('s5')
    assert pdf is None, 'No PDF should be stored on failure'
    assert email_called['n'] == 0, 'Email must not be sent on PDF failure'
