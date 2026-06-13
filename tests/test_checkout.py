"""Tests for POST /checkout/{session_id} — Dodo Payments checkout creation."""
import pytest


@pytest.mark.asyncio
async def test_checkout_unconfigured_503(api):
    r = await api.post('/checkout/any-id')
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_checkout_unknown_id_404(api, mock_db, monkeypatch):
    monkeypatch.setenv('DODO_API_KEY', 'dodo_test_dummy')
    monkeypatch.setenv('DODO_PRODUCT_ID', 'prod_dummy')
    r = await api.post('/checkout/no-such-id')
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_checkout_not_complete_409(api, mock_db, monkeypatch):
    monkeypatch.setenv('DODO_API_KEY', 'dodo_test_dummy')
    monkeypatch.setenv('DODO_PRODUCT_ID', 'prod_dummy')
    await mock_db['sessions'].insert_one({'_id': 'co1', 'status': 'processing'})
    r = await api.post('/checkout/co1')
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_checkout_already_paid_409(api, mock_db, monkeypatch):
    monkeypatch.setenv('DODO_API_KEY', 'dodo_test_dummy')
    monkeypatch.setenv('DODO_PRODUCT_ID', 'prod_dummy')
    await mock_db['sessions'].insert_one({'_id': 'co2', 'status': 'complete', 'paid': True})
    r = await api.post('/checkout/co2')
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_checkout_awaiting_payment_allowed(api, mock_db, monkeypatch):
    monkeypatch.setenv('DODO_API_KEY', 'dodo_test_dummy')
    monkeypatch.setenv('DODO_PRODUCT_ID', 'prod_dummy')
    await mock_db['sessions'].insert_one({
        '_id': 'co-ap',
        'status': 'awaiting_payment',
        'paid': False,
        'tier': 'owner_manual',
        'source_meta': {'url': 'github.com/user/big-repo', 'filename': None},
        'analysis': {},
    })

    async def _fake_checkout(**kwargs):
        return 'https://test.dodopayments.com/session/cks_ap'

    monkeypatch.setattr('app.routers.checkout.create_checkout_session', _fake_checkout)

    r = await api.post('/checkout/co-ap')
    assert r.status_code == 200
    assert r.json()['checkout_url'] == 'https://test.dodopayments.com/session/cks_ap'


@pytest.mark.asyncio
async def test_checkout_processing_still_409(api, mock_db, monkeypatch):
    monkeypatch.setenv('DODO_API_KEY', 'dodo_test_dummy')
    monkeypatch.setenv('DODO_PRODUCT_ID', 'prod_dummy')
    await mock_db['sessions'].insert_one({'_id': 'co-proc', 'status': 'processing', 'paid': False})
    r = await api.post('/checkout/co-proc')
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_checkout_happy_path(api, mock_db, monkeypatch):
    monkeypatch.setenv('DODO_API_KEY', 'dodo_test_dummy')
    monkeypatch.setenv('DODO_PRODUCT_ID', 'prod_dummy')
    await mock_db['sessions'].insert_one({
        '_id': 'co3',
        'status': 'complete',
        'paid': False,
        'analysis': {'repo_name': 'my-repo'},
    })

    async def _fake_checkout(**kwargs):
        return 'https://test.dodopayments.com/session/cks_x'

    monkeypatch.setattr('app.routers.checkout.create_checkout_session', _fake_checkout)

    r = await api.post('/checkout/co3')
    assert r.status_code == 200
    data = r.json()
    assert data['checkout_url'] == 'https://test.dodopayments.com/session/cks_x'
    assert 'test_mode' in data
