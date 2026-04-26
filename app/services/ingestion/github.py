import base64
from urllib.parse import urlparse

import httpx

from app.models.analysis import RepoFile
from app.services.ingestion.file_filter import is_text_bytes, should_include
from app.services.ingestion.zip_handler import ingest_zip_bytes

ALLOWED_HOSTS = {'github.com', 'gitlab.com', 'bitbucket.org'}


class RepoIngestionError(Exception):
    pass


def validate_repo_url(url: str) -> tuple[str, list[str]]:
    parsed = urlparse(url)
    if parsed.scheme not in {'https'}:
        raise RepoIngestionError('Only HTTPS repository URLs are allowed.')
    if parsed.hostname not in ALLOWED_HOSTS:
        raise RepoIngestionError('Only github.com, gitlab.com, bitbucket.org are allowed.')
    parts = [p for p in parsed.path.split('/') if p]
    if len(parts) < 2:
        raise RepoIngestionError('Repository URL must include owner and repo name.')
    return parsed.hostname, parts


async def ingest_repo_url(url: str, github_limit_mb: int) -> tuple[list[RepoFile], dict]:
    host, parts = validate_repo_url(url)
    if host == 'github.com':
        files, meta = await _ingest_github(parts, github_limit_mb)
    elif host == 'gitlab.com':
        files, meta = await _ingest_gitlab(parts)
    else:
        files, meta = await _ingest_bitbucket(parts)
    return files, meta


async def _ingest_github(parts: list[str], github_limit_mb: int) -> tuple[list[RepoFile], dict]:
    from app.config import get_settings
    owner, repo = parts[0], parts[1].removesuffix('.git')
    settings = get_settings()
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'CodeReceipt'}
    if settings.github_token:
        headers['Authorization'] = f'Bearer {settings.github_token}'
    async with httpx.AsyncClient(timeout=30) as client:
        repo_resp = await client.get(f'https://api.github.com/repos/{owner}/{repo}', headers=headers)
        if repo_resp.status_code != 200:
            raise RepoIngestionError('Unable to access GitHub repository metadata.')
        repo_data = repo_resp.json()
        size_kb = repo_data.get('size', 0)
        if size_kb > github_limit_mb * 1024:
            raise RepoIngestionError(f'GitHub repository exceeds {github_limit_mb}MB limit.')
        default_branch = repo_data.get('default_branch', 'main')

        tree_resp = await client.get(
            f'https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1',
            headers=headers,
        )
        if tree_resp.status_code != 200:
            raise RepoIngestionError('Unable to fetch repository tree.')
        tree = tree_resp.json().get('tree', [])

        files: list[RepoFile] = []
        total_bytes = 0
        for item in tree:
            if item.get('type') != 'blob':
                continue
            path = item.get('path', '')
            if not should_include(path):
                continue
            if len(files) >= 500:
                break
            blob = await client.get(item['url'], headers=headers)
            if blob.status_code != 200:
                continue
            content_encoded = blob.json().get('content', '')
            if not content_encoded:
                continue
            content = base64.b64decode(content_encoded)
            if not is_text_bytes(content):
                continue
            text = content.decode('utf-8', errors='ignore')
            files.append(RepoFile(path=path, content=text))
            total_bytes += len(content)

        return files, {'url': f'https://github.com/{owner}/{repo}', 'file_count': len(files), 'total_bytes': total_bytes}


async def _ingest_gitlab(parts: list[str]) -> tuple[list[RepoFile], dict]:
    project = '/'.join(parts[:2]).removesuffix('.git')
    encoded = httpx.QueryParams({'id': project}).get('id')
    archive_url = f'https://gitlab.com/{project}/-/archive/main/{parts[1]}-main.zip'
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(archive_url)
        if resp.status_code != 200:
            raise RepoIngestionError('Unable to fetch GitLab archive.')
    files, total_bytes = await ingest_zip_bytes(resp.content, 25)
    return files, {'url': f'https://gitlab.com/{project}', 'file_count': len(files), 'total_bytes': total_bytes, 'project': encoded}


async def _ingest_bitbucket(parts: list[str]) -> tuple[list[RepoFile], dict]:
    workspace, repo = parts[0], parts[1].removesuffix('.git')
    archive_url = f'https://bitbucket.org/{workspace}/{repo}/get/main.zip'
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        resp = await client.get(archive_url)
        if resp.status_code != 200:
            raise RepoIngestionError('Unable to fetch Bitbucket archive.')
    files, total_bytes = await ingest_zip_bytes(resp.content, 25)
    return files, {'url': f'https://bitbucket.org/{workspace}/{repo}', 'file_count': len(files), 'total_bytes': total_bytes}
