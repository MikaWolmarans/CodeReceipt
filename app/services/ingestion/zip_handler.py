from __future__ import annotations

from io import BytesIO
from zipfile import BadZipFile, ZipFile

from app.models.analysis import RepoFile
from app.services.ingestion.file_filter import is_text_bytes, should_include


class ZipValidationError(Exception):
    pass


async def ingest_zip_bytes(data: bytes, max_zip_size_mb: int) -> tuple[list[RepoFile], int]:
    if len(data) > max_zip_size_mb * 1024 * 1024:
        raise ZipValidationError(f'ZIP exceeds {max_zip_size_mb}MB limit.')

    try:
        zf = ZipFile(BytesIO(data))
    except BadZipFile as exc:
        raise ZipValidationError('Invalid ZIP file.') from exc

    infos = zf.infolist()
    if len(infos) > 500:
        raise ZipValidationError('ZIP contains too many files (max 500).')

    total_uncompressed = sum(i.file_size for i in infos)
    total_compressed = max(sum(i.compress_size for i in infos), 1)
    ratio = total_uncompressed / total_compressed
    if ratio > 100 or total_uncompressed > 200 * 1024 * 1024:
        raise ZipValidationError('ZIP bomb protection triggered.')

    files: list[RepoFile] = []
    total_bytes = 0
    for info in infos:
        if info.is_dir() or not should_include(info.filename):
            continue
        content = zf.read(info.filename)
        if not is_text_bytes(content):
            continue
        text = content.decode('utf-8', errors='ignore')
        files.append(RepoFile(path=info.filename, content=text))
        total_bytes += len(content)
        if len(files) > 500:
            raise ZipValidationError('File cap exceeded (500).')

    return files, total_bytes
