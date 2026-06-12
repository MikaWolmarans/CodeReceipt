import os

os.environ.setdefault('MONGODB_URI', 'mongodb://localhost:27017/codereceipt_test')
os.environ.setdefault('FRONTEND_URL', 'https://test.codereceipt.local')
os.environ.setdefault('LLM_API_KEY', 'test-key')

import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient


@pytest.fixture()
def mock_db(monkeypatch):
    """Swap session_service's Motor collections for in-memory mongomock ones."""
    from app.services.session import session_service

    client = AsyncMongoMockClient()
    db = client['codereceipt_test']
    monkeypatch.setattr(session_service, 'client', client)
    monkeypatch.setattr(session_service, 'db', db)
    monkeypatch.setattr(session_service, 'sessions', db['sessions'])
    monkeypatch.setattr(session_service, 'counters', db['daily_counters'])
    monkeypatch.setattr(session_service, 'pdf_store', db['pdf_store'])
    monkeypatch.setattr(session_service, 'customers', db['customers'])
    return db


@pytest.fixture()
async def api(mock_db):
    from app.services.session import session_service
    from app.main import app

    async def _noop_ensure_indexes():
        pass

    monkeypatch_holder = {}

    original = session_service.ensure_indexes
    session_service.ensure_indexes = _noop_ensure_indexes

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        yield client

    session_service.ensure_indexes = original
