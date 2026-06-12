from __future__ import annotations

import json
from pathlib import Path

from app.models.analysis import RepoFile


def detect_stack(files: list[RepoFile]) -> dict[str, list[str]]:
    languages: set[str] = set()
    frameworks: set[str] = set()
    databases: set[str] = set()
    third_parties: set[str] = set()

    for rf in files:
        suffix = Path(rf.path).suffix.lower()
        if suffix == '.py':
            languages.add('Python')
        elif suffix in {'.js', '.jsx'}:
            languages.add('JavaScript')
        elif suffix in {'.ts', '.tsx'}:
            languages.add('TypeScript')
        elif suffix == '.go':
            languages.add('Go')
        elif suffix == '.rs':
            languages.add('Rust')
        elif suffix == '.java':
            languages.add('Java')
        elif suffix == '.rb':
            languages.add('Ruby')
        elif suffix == '.php':
            languages.add('PHP')

        name = Path(rf.path).name
        if name == 'package.json':
            try:
                data = json.loads(rf.content)
                deps = {**data.get('dependencies', {}), **data.get('devDependencies', {})}
                if 'react' in deps:
                    frameworks.add('React')
                if 'next' in deps:
                    frameworks.add('Next.js')
                if 'vue' in deps:
                    frameworks.add('Vue')
                if 'fastapi' in deps:
                    frameworks.add('FastAPI')
                if 'express' in deps:
                    frameworks.add('Express')
                third_parties.update(list(deps.keys())[:20])
            except json.JSONDecodeError:
                pass
        elif name == 'requirements.txt':
            lines = [x.strip().lower() for x in rf.content.splitlines() if x.strip()]
            if any('django' in l for l in lines):
                frameworks.add('Django')
            if any('fastapi' in l for l in lines):
                frameworks.add('FastAPI')
            if any('flask' in l for l in lines):
                frameworks.add('Flask')
            if any('pymongo' in l or 'motor' in l for l in lines):
                databases.add('MongoDB')
        elif name == 'go.mod':
            languages.add('Go')
        elif name == 'dockerfile':
            frameworks.add('Docker')

        lower = rf.content.lower()
        if any(db in lower for db in ['mongodb', 'pymongo', 'mongoose']):
            databases.add('MongoDB')
        if any(db in lower for db in ['postgres', 'psycopg', 'sequelize']):
            databases.add('PostgreSQL')
        if 'redis' in lower:
            databases.add('Redis')

    return {
        'languages': sorted(languages),
        'frameworks': sorted(frameworks),
        'databases': sorted(databases),
        'third_parties': sorted(third_parties)[:30],
    }
