"""Tests for GET /export/{session_id} — payment gate."""
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
