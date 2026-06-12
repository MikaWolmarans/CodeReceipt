"""Tests for /analyse tier gates — size gate, file count gate, truncation recording."""
import pytest
from app.models.analysis import RepoFile
from app.services.session import session_service

# Synthetic files
_SMALL_FILES = [RepoFile(path=f'f{i}.py', content='x') for i in range(5)]
_MANY_FILES = [RepoFile(path=f'f{i}.py', content='x') for i in range(30)]


def _fake_ingest_url(files, total_bytes=1000):
    async def _impl(url, max_mb):
        return files, {'url': url, 'total_bytes': total_bytes, 'file_count': len(files)}
    return _impl


def _fake_ingest_zip(files, total_bytes=1000):
    async def _impl(data, max_mb):
        return files, total_bytes
    return _impl


async def _noop_analysis(session_id, files, repo_name):
    from app.services.session import session_service
    await session_service.update_session(session_id, status='complete', progress=100,
                                          analysis={'repo_name': repo_name, 'chunks': [], 'synthesis': {}})


@pytest.mark.asyncio
async def test_url_over_size_limit_creates_awaiting_payment_session(api, mock_db, mock_uploads, monkeypatch):
    over_limit_bytes = 6 * 1024 * 1024  # 6 MB > 5 MB default
    monkeypatch.setattr('app.routers.ingest.ingest_repo_url',
                        _fake_ingest_url(_SMALL_FILES, total_bytes=over_limit_bytes))
    monkeypatch.setattr('app.routers.ingest._run_analysis', _noop_analysis)

    r = await api.post('/analyse', data={'url': 'github.com/user/big-repo'})
    assert r.status_code == 200
    body = r.json()
    assert body['requires_upgrade'] is True
    assert body['session_id'] is not None

    session = await session_service.get_session(body['session_id'])
    assert session is not None
    assert session['status'] == 'awaiting_payment'
    assert session['tier'] == 'owner_manual'


@pytest.mark.asyncio
async def test_zip_over_size_limit_stores_upload(api, mock_db, mock_uploads, monkeypatch):
    over_limit_bytes = 6 * 1024 * 1024
    monkeypatch.setattr('app.routers.ingest.ingest_zip_bytes',
                        _fake_ingest_zip(_SMALL_FILES, total_bytes=over_limit_bytes))
    monkeypatch.setattr('app.routers.ingest._run_analysis', _noop_analysis)

    import io
    zip_bytes = b'PK\x03\x04' + b'0' * 100  # fake zip header
    r = await api.post('/analyse', files={'zip_file': ('repo.zip', io.BytesIO(zip_bytes), 'application/zip')})
    assert r.status_code == 200
    body = r.json()
    assert body['requires_upgrade'] is True
    sid = body['session_id']
    assert sid is not None

    session = await session_service.get_session(sid)
    assert session['upload_stored'] is True
    assert sid in mock_uploads


@pytest.mark.asyncio
async def test_many_files_records_truncation(api, mock_db, mock_uploads, monkeypatch):
    monkeypatch.setattr('app.routers.ingest.ingest_repo_url',
                        _fake_ingest_url(_MANY_FILES, total_bytes=1000))
    monkeypatch.setattr('app.routers.ingest._run_analysis', _noop_analysis)

    r = await api.post('/analyse', data={'url': 'github.com/user/many-files'})
    assert r.status_code == 200
    sid = r.json()['session_id']

    session = await session_service.get_session(sid)
    assert session['truncated'] is True
    assert session['total_file_count'] == 30


@pytest.mark.asyncio
async def test_small_repo_not_truncated(api, mock_db, mock_uploads, monkeypatch):
    monkeypatch.setattr('app.routers.ingest.ingest_repo_url',
                        _fake_ingest_url(_SMALL_FILES, total_bytes=1000))
    monkeypatch.setattr('app.routers.ingest._run_analysis', _noop_analysis)

    r = await api.post('/analyse', data={'url': 'github.com/user/small-repo'})
    assert r.status_code == 200
    sid = r.json()['session_id']

    session = await session_service.get_session(sid)
    assert session.get('truncated', False) is False
    assert sid not in mock_uploads
