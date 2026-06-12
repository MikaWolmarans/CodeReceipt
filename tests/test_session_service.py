"""Tests for SessionService — daily counters, pdf store, customer tracking."""
import pytest
from app.services.session import session_service


@pytest.mark.asyncio
async def test_increment_free_counter_allows_up_to_cap(mock_db):
    cap = session_service.settings.max_free_analyses_per_day
    for i in range(cap):
        result = await session_service.increment_free_daily_or_reject()
        assert result is True, f'Call {i + 1} should be allowed (cap={cap})'

    # One more should be rejected
    result = await session_service.increment_free_daily_or_reject()
    assert result is False, 'Call beyond cap should return False'


@pytest.mark.asyncio
async def test_increment_daily_cap_or_reject(mock_db):
    cap = session_service.settings.max_daily_analyses
    for i in range(cap):
        result = await session_service.increment_daily_cap_or_reject()
        assert result is True, f'Call {i + 1} should be allowed (cap={cap})'

    result = await session_service.increment_daily_cap_or_reject()
    assert result is False


@pytest.mark.asyncio
async def test_both_counters_share_one_document_per_date(mock_db):
    # Pins the fix from commit eb5bf21 — single doc with both fields
    await session_service.increment_free_daily_or_reject()
    await session_service.increment_daily_cap_or_reject()

    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    docs = await mock_db['daily_counters'].find({'date': today}).to_list(None)
    assert len(docs) == 1
    assert 'free_count' in docs[0]
    assert 'count' in docs[0]


@pytest.mark.asyncio
async def test_store_and_get_pdf_round_trip(mock_db):
    await session_service.store_pdf('sess1', b'%PDF-fake', 'my-repo')
    result = await session_service.get_pdf('sess1')
    assert result == b'%PDF-fake'


@pytest.mark.asyncio
async def test_get_pdf_returns_none_for_unknown(mock_db):
    result = await session_service.get_pdf('does-not-exist')
    assert result is None


@pytest.mark.asyncio
async def test_record_customer_idempotent_no_duplicate_key(mock_db):
    await session_service.record_customer('user@example.com', 'sess-a')
    await session_service.record_customer('user@example.com', 'sess-b')

    docs = await mock_db['customers'].find({'email': 'user@example.com'}).to_list(None)
    assert len(docs) == 1
    assert set(docs[0]['session_ids']) == {'sess-a', 'sess-b'}
