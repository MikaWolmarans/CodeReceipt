#!/usr/bin/env python3
"""CodeReceipt: deterministic repo scanner (zero dependencies, stdlib only).

Walks a codebase and emits a structured JSON "facts" object: the stack, a file
map, discovered environment-variable names, likely entry points, and config
files. It does NOT call any AI model and never sends code anywhere. It just
gathers the objective facts an agent needs to write the manual.

Usage:
    python3 scan.py [ROOT] [-o facts.json]

    ROOT   directory to scan (default: current directory)
    -o     write JSON here instead of stdout
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ── File selection (ported from CodeReceipt's ingestion filter) ───────────────
ALLOWED_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.json', '.yaml',
    '.yml', '.md', '.rb', '.go', '.rs', '.java', '.php', '.txt', '.ini', '.cfg',
    '.toml', '.xml', '.sh', '.sql', '.dart', '.kt', '.swift', '.cs',
}
EXCLUDED_DIRS = {
    'node_modules', '.git', 'dist', 'build', 'vendor', '__pycache__', '.venv',
    'venv', '.next', '.nuxt', 'coverage', '.mypy_cache', '.pytest_cache',
    '.idea', '.vscode', 'target', '.expo', 'Pods',
}
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.zip', '.tar', '.gz',
    '.7z', '.exe', '.dll', '.so', '.dylib', '.bin', '.ico', '.woff', '.woff2',
    '.ttf', '.mp4', '.mov', '.mp3',
}
MAX_FILE_BYTES = 400_000       # skip anything larger (likely generated/minified)
MAX_FILES_IN_MAP = 400          # cap the emitted file map so facts.json stays sane


def should_include(path: Path) -> bool:
    parts = {p.lower() for p in path.parts}
    if parts & EXCLUDED_DIRS:
        return False
    name = path.name.lower()
    if name.startswith('.env'):        # never surface secret files
        return False
    suffix = path.suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        return False
    if suffix and suffix in ALLOWED_EXTENSIONS:
        return True
    # extension-less files that are commonly config/scripts
    return suffix == '' and name in {
        'dockerfile', 'makefile', 'procfile', 'gemfile', 'rakefile', 'caddyfile',
    }


def read_text(path: Path) -> str | None:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return None
        blob = path.read_bytes()
    except (OSError, ValueError):
        return None
    if b'\x00' in blob:
        return None
    try:
        return blob.decode('utf-8')
    except UnicodeDecodeError:
        return None


# ── Stack detection (ported from CodeReceipt's stack_detect) ──────────────────
LANG_BY_SUFFIX = {
    '.py': 'Python', '.js': 'JavaScript', '.jsx': 'JavaScript', '.ts': 'TypeScript',
    '.tsx': 'TypeScript', '.go': 'Go', '.rs': 'Rust', '.java': 'Java', '.rb': 'Ruby',
    '.php': 'PHP', '.dart': 'Dart', '.kt': 'Kotlin', '.swift': 'Swift', '.cs': 'C#',
}


def detect_stack(files: list[dict]) -> dict:
    languages: set[str] = set()
    frameworks: set[str] = set()
    databases: set[str] = set()
    third_parties: set[str] = set()

    for f in files:
        path, content = f['path'], f['content']
        suffix = Path(path).suffix.lower()
        if suffix in LANG_BY_SUFFIX:
            languages.add(LANG_BY_SUFFIX[suffix])

        name = Path(path).name.lower()
        if name == 'package.json':
            try:
                data = json.loads(content)
                deps = {**data.get('dependencies', {}), **data.get('devDependencies', {})}
                if 'react' in deps: frameworks.add('React')
                if 'next' in deps: frameworks.add('Next.js')
                if 'vue' in deps: frameworks.add('Vue')
                if 'svelte' in deps: frameworks.add('Svelte')
                if 'express' in deps: frameworks.add('Express')
                if '@angular/core' in deps: frameworks.add('Angular')
                third_parties.update(list(deps.keys())[:25])
            except (json.JSONDecodeError, AttributeError):
                pass
        elif name == 'requirements.txt' or name == 'pyproject.toml':
            low = content.lower()
            if 'django' in low: frameworks.add('Django')
            if 'fastapi' in low: frameworks.add('FastAPI')
            if 'flask' in low: frameworks.add('Flask')
            if 'pymongo' in low or 'motor' in low: databases.add('MongoDB')
        elif name == 'go.mod':
            languages.add('Go')
        elif name == 'dockerfile':
            frameworks.add('Docker')

        low = content.lower()
        if any(k in low for k in ('mongodb', 'pymongo', 'mongoose')): databases.add('MongoDB')
        if any(k in low for k in ('postgres', 'psycopg', 'sequelize')): databases.add('PostgreSQL')
        if 'mysql' in low: databases.add('MySQL')
        if 'sqlite' in low: databases.add('SQLite')
        if 'redis' in low: databases.add('Redis')

    return {
        'languages': sorted(languages),
        'frameworks': sorted(frameworks),
        'databases': sorted(databases),
        'third_parties': sorted(third_parties)[:30],
    }


# ── Environment variable discovery ────────────────────────────────────────────
ENV_PATTERNS = [
    re.compile(r'os\.environ(?:\.get)?\(\s*[\'"]([A-Z][A-Z0-9_]{2,})[\'"]'),
    re.compile(r'os\.getenv\(\s*[\'"]([A-Z][A-Z0-9_]{2,})[\'"]'),
    re.compile(r'process\.env\.([A-Z][A-Z0-9_]{2,})'),
    re.compile(r'process\.env\[\s*[\'"]([A-Z][A-Z0-9_]{2,})[\'"]'),
    re.compile(r'[Ff]ield\([^)]*alias\s*=\s*[\'"]([A-Z][A-Z0-9_]{2,})[\'"]'),
    re.compile(r'import\.meta\.env\.([A-Z][A-Z0-9_]{2,})'),
]


def discover_env_vars(files: list[dict]) -> list[str]:
    found: set[str] = set()
    for f in files:
        for pat in ENV_PATTERNS:
            found.update(pat.findall(f['content']))
    # drop obvious noise
    found.discard('PATH')
    return sorted(found)


# ── Entry-point heuristics ────────────────────────────────────────────────────
ENTRY_HINTS = (
    'main.py', 'app.py', 'manage.py', 'wsgi.py', 'asgi.py', 'server.py',
    'index.js', 'index.ts', 'main.js', 'main.ts', 'server.js', 'app.js',
    'main.go', 'main.rs', 'index.html', 'cli.py', '__main__.py',
)


def find_entry_points(files: list[dict]) -> list[str]:
    hits = []
    for f in files:
        name = Path(f['path']).name.lower()
        depth = Path(f['path']).as_posix().count('/')
        if name in ENTRY_HINTS and depth <= 2:
            hits.append(f['path'])
    return sorted(set(hits))


def summarise_head(content: str, limit: int = 200) -> str:
    """First meaningful non-blank, non-import line: a cheap purpose hint."""
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith(('import ', 'from ', '//', '#!', '/*', '*')):
            continue
        s = s.lstrip('#/* ').strip()
        if s:
            return s[:limit]
    return ''


def main() -> int:
    ap = argparse.ArgumentParser(description='Scan a repo into a structured facts JSON.')
    ap.add_argument('root', nargs='?', default='.', help='directory to scan')
    ap.add_argument('-o', '--output', help='write JSON here instead of stdout')
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f'error: {root} is not a directory', file=sys.stderr)
        return 1

    files: list[dict] = []
    total_lines = 0
    skipped_large = 0
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if not should_include(rel):
            continue
        content = read_text(path)
        if content is None:
            skipped_large += 1
            continue
        line_count = content.count('\n') + 1
        total_lines += line_count
        files.append({'path': rel.as_posix(), 'content': content, 'lines': line_count})

    stack = detect_stack(files)
    env_vars = discover_env_vars(files)
    entry_points = find_entry_points(files)

    # Sort the file map by size (biggest = usually most important), then cap it.
    files_sorted = sorted(files, key=lambda f: f['lines'], reverse=True)
    file_map = [
        {'path': f['path'], 'lines': f['lines'], 'hint': summarise_head(f['content'])}
        for f in files_sorted[:MAX_FILES_IN_MAP]
    ]

    config_files = sorted(
        f['path'] for f in files
        if Path(f['path']).name.lower() in {
            'package.json', 'requirements.txt', 'pyproject.toml', 'go.mod',
            'cargo.toml', 'dockerfile', 'docker-compose.yml', 'docker-compose.yaml',
            'makefile', 'procfile', 'tsconfig.json', 'vite.config.js', 'vite.config.ts',
            'next.config.js', '.gitignore',
        }
    )

    facts = {
        'repo_name': root.name,
        'scanned_files': len(files),
        'files_omitted_from_map': max(0, len(files) - len(file_map)),
        'skipped_large_or_binary': skipped_large,
        'total_lines': total_lines,
        'stack': stack,
        'entry_points': entry_points,
        'config_files': config_files,
        'env_vars': env_vars,
        'file_map': file_map,
        '_note': (
            'Generated by CodeReceipt scan.py: objective facts only, no AI. '
            'The agent reading this should open the highest-signal files, then '
            'write CLAUDE.md and MANUAL.md per the skill instructions.'
        ),
    }

    payload = json.dumps(facts, indent=2)
    if args.output:
        Path(args.output).write_text(payload, encoding='utf-8')
        print(f'Wrote {args.output}: {len(files)} files, {total_lines} lines, '
              f'{len(env_vars)} env vars, stack: {stack["languages"]}', file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
