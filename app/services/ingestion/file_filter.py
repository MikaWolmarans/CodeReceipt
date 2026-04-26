from pathlib import Path

ALLOWED_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.json', '.yaml', '.yml', '.md', '.rb', '.go', '.rs', '.java',
    '.php', '.txt', '.ini', '.cfg', '.toml', '.xml', '.sh', '.sql', '.dart', '.kt', '.swift', '.cs'
}

EXCLUDED_DIRS = {'node_modules', '.git', 'dist', 'build', 'vendor', '__pycache__'}
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.zip', '.tar', '.gz', '.7z', '.exe', '.dll', '.so', '.dylib', '.bin', '.ico'
}


def should_include(path: str) -> bool:
    lower = path.lower()
    p = Path(lower)
    if any(part in EXCLUDED_DIRS for part in p.parts):
        return False
    if p.name.startswith('.env'):
        return False
    if p.suffix in BINARY_EXTENSIONS:
        return False
    if p.suffix and p.suffix in ALLOWED_EXTENSIONS:
        return True
    return p.suffix == ''


def is_text_bytes(blob: bytes) -> bool:
    if b'\x00' in blob:
        return False
    try:
        blob.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False
