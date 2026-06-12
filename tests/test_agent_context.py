"""Tests for build_agent_context and GET /export/{session_id}/agent-context."""
import pytest
from app.services.agent_context import build_agent_context
from app.services.session import session_service


def _session(synthesis, repo_name='my-repo'):
    return {
        'status': 'complete',
        'paid': True,
        'analysis': {'repo_name': repo_name, 'synthesis': synthesis},
    }


def test_build_agent_context_returns_string():
    s = _session({'what_you_built': 'A FastAPI app', 'architecture_overview': 'Monolith'})
    result = build_agent_context(s)
    assert isinstance(result, str)
    assert 'my-repo' in result
    assert 'A FastAPI app' in result


def test_build_agent_context_no_raw_json_leak():
    s = _session({'what_you_built': {'key': 'value'}})  # dict instead of string
    result = build_agent_context(s)
    assert '[object Object]' not in result
    assert '{"key"' not in result


def test_build_agent_context_list_quick_start():
    s = _session({'next_actions': ['Add tests', 'Deploy to prod']})
    result = build_agent_context(s)
    assert 'Add tests' in result
    assert 'Deploy to prod' in result


def test_build_agent_context_risk_register():
    s = _session({
        'risk_register': [{'description': 'No auth on /admin', 'severity': 'high'}],
        'warning_lights': ['Missing rate limiting'],
    })
    result = build_agent_context(s)
    assert 'No auth on /admin' in result
    assert 'Missing rate limiting' in result


@pytest.mark.asyncio
async def test_export_agent_context_unpaid_402(api, mock_db):
    await mock_db['sessions'].insert_one({
        '_id': 'ac1',
        'status': 'complete',
        'paid': False,
        'analysis': {'repo_name': 'repo', 'synthesis': {}},
    })
    r = await api.get('/export/ac1/agent-context')
    assert r.status_code == 402


@pytest.mark.asyncio
async def test_export_agent_context_paid_200(api, mock_db):
    await mock_db['sessions'].insert_one({
        '_id': 'ac2',
        'status': 'complete',
        'paid': True,
        'analysis': {'repo_name': 'test-repo', 'synthesis': {'what_you_built': 'A CLI tool'}},
    })
    r = await api.get('/export/ac2/agent-context')
    assert r.status_code == 200
    assert 'text/markdown' in r.headers['content-type']
    assert 'CLAUDE.md' in r.headers.get('content-disposition', '')
    assert 'test-repo' in r.text


@pytest.mark.asyncio
async def test_export_agent_context_stored_survives_session_ttl(api, mock_db):
    """Stored agent context in pdf_store survives after session expires."""
    await session_service.store_agent_context('ac3', '# my-repo — Agent Context\n\nHello')

    r = await api.get('/export/ac3/agent-context')
    assert r.status_code == 200
    assert 'Agent Context' in r.text
