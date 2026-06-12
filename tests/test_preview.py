"""Tests for GET /preview/{session_id} — type coercion and section counts."""
import pytest


def _session(owner_quick_start, risk_register=None, warning_lights=None):
    return {
        'status': 'complete',
        'analysis': {
            'repo_name': 'test-repo',
            'chunks': [1, 2, 3],
            'synthesis': {
                'owner_quick_start': owner_quick_start,
                'risk_register': risk_register or [],
                'warning_lights': warning_lights or [],
                'key_systems': [],
                'environment_variables': [],
                'running_costs': [],
            },
        },
        'stack': {},
        'paid': False,
    }


@pytest.mark.asyncio
async def test_preview_unknown_id_404(api):
    r = await api.get('/preview/no-such-id')
    assert r.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize('quick_start,label', [
    ('x' * 300, 'long string'),
    (['step one', 'step two'], 'list'),
    ({'what_it_does': 'build apps', 'who_uses_it': 'devs'}, 'dict'),
])
async def test_preview_quick_start_coercion(api, mock_db, quick_start, label):
    doc = _session(quick_start)
    doc['_id'] = f'qs-{label}'
    await mock_db['sessions'].insert_one(doc)

    r = await api.get(f'/preview/qs-{label}')
    assert r.status_code == 200, f'Expected 200 for {label}, got {r.status_code}'
    body = r.json()
    assert isinstance(body['quick_start_preview'], str), f'quick_start_preview not a string for {label}'
    assert len(body['quick_start_preview']) <= 221, f'preview too long for {label}'


@pytest.mark.asyncio
async def test_preview_pdf_ready_on_complete_fulfillment(api, mock_db):
    doc = _session('hello')
    doc['_id'] = 'pr-complete'
    doc['paid'] = True
    doc['fulfillment_status'] = 'complete'
    await mock_db['sessions'].insert_one(doc)

    r = await api.get('/preview/pr-complete')
    assert r.status_code == 200
    assert r.json()['pdf_ready'] is True


@pytest.mark.asyncio
async def test_preview_pdf_not_ready_without_fulfillment(api, mock_db):
    doc = _session('hello')
    doc['_id'] = 'pr-pending'
    doc['paid'] = True
    await mock_db['sessions'].insert_one(doc)

    r = await api.get('/preview/pr-pending')
    assert r.status_code == 200
    assert r.json()['pdf_ready'] is False


@pytest.mark.asyncio
async def test_preview_section_counts(api, mock_db):
    doc = _session('hello', risk_register=['r1', 'r2'], warning_lights=['w1'])
    doc['_id'] = 'sc-sess'
    await mock_db['sessions'].insert_one(doc)

    r = await api.get('/preview/sc-sess')
    assert r.status_code == 200
    assert r.json()['section_counts']['risks'] == 3
