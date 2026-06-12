"""Tests for GET /export/{session_id} — payment gate and pdf_store fallback."""
import pytest
from app.services.session import session_service


@pytest.mark.asyncio
async def test_export_unknown_id_404(api):
    r = await api.get('/export/no-such-id')
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_export_processing_409(api, mock_db):
    await mock_db['sessions'].insert_one({'_id': 's1', 'status': 'processing'})
    r = await api.get('/export/s1')
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_export_unpaid_402(api, mock_db):
    await mock_db['sessions'].insert_one({'_id': 's2', 'status': 'complete', 'paid': False})
    r = await api.get('/export/s2')
    assert r.status_code == 402


@pytest.mark.asyncio
async def test_export_paid_200(api, mock_db):
    await mock_db['sessions'].insert_one({
        '_id': 's3',
        'status': 'complete',
        'paid': True,
        'analysis': {'repo_name': 'my-repo'},
    })
    await session_service.store_pdf('s3', b'%PDF-test', 'my-repo')

    r = await api.get('/export/s3')
    assert r.status_code == 200
    assert r.headers['content-type'] == 'application/pdf'
    assert r.content[:4] == b'%PDF'


@pytest.mark.asyncio
async def test_export_paid_awaiting_payment_409(api, mock_db, monkeypatch):
    """Paid session still in awaiting_payment (fulfillment not yet complete) → 409."""
    await mock_db['sessions'].insert_one({
        '_id': 'ap1',
        'status': 'awaiting_payment',
        'paid': True,
        'analysis': {},
    })

    async def _no_render(session):
        raise AssertionError('build_pdf_bytes must not be called for awaiting_payment sessions')

    monkeypatch.setattr('app.routers.export.build_pdf_bytes', _no_render)

    r = await api.get('/export/ap1')
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_export_expired_paid_session_falls_back_to_pdf_store(api, mock_db):
    # No session doc (simulates 2h TTL expiry), but PDF stored (30-day TTL)
    await session_service.store_pdf('gone1', b'%PDF-archived', 'my-repo')

    r = await api.get('/export/gone1')
    assert r.status_code == 200
    assert r.headers['content-type'] == 'application/pdf'
    assert r.content == b'%PDF-archived'
    assert 'my-repo-owners-manual.pdf' in r.headers.get('content-disposition', '')


@pytest.mark.asyncio
async def test_export_expired_unpaid_session_404(api, mock_db):
    # No session doc, no pdf_store doc — proves fallback cannot bypass 402 gate
    r = await api.get('/export/gone2')
    assert r.status_code == 404
