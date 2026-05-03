from __future__ import annotations

import html
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import chevron
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright


class PdfRenderError(Exception):
    pass


TEMPLATE_PATH = Path(__file__).parent / 'template.html'


def _text(value: Any, fallback: str = '') -> str:
    if value is None:
        return fallback
    return str(value).strip() or fallback


def _sentence(value: Any, fallback: str) -> str:
    value = _text(value)
    return value if value else fallback


def _repo_display_name(repo_name: str) -> tuple[str, str, str]:
    cleaned = re.sub(r'[-_]+', ' ', repo_name).strip() or 'Repository'
    parts = cleaned.split()
    display = ''.join(word[:1].upper() + word[1:] for word in parts)
    match = re.match(r'(.+?)([A-Z][a-z0-9]+)$', display)
    if match:
        return display, match.group(1), match.group(2)
    if len(parts) > 1:
        accent = parts[-1][:1].upper() + parts[-1][1:]
        main = display[: -len(accent)]
        return display, main, accent
    return display, display, ''


def _stack_summary(stack: dict[str, Any]) -> str:
    items: list[str] = []
    for key in ('frameworks', 'languages', 'databases'):
        values = stack.get(key) or []
        items.extend(_text(v) for v in values[:3] if _text(v))
    return ' · '.join(dict.fromkeys(items)) or 'Software Project'


def _stack_badges(stack: dict[str, Any]) -> list[dict[str, Any]]:
    badges: list[dict[str, Any]] = []
    for key in ('frameworks', 'languages', 'databases', 'third_parties'):
        for value in stack.get(key) or []:
            name = _text(value)
            if name and name not in {b['name'] for b in badges}:
                badges.append({'name': name, 'highlight': key in {'frameworks', 'languages'}})
    return badges[:10] or [{'name': 'Codebase', 'highlight': True}]


def _file_tree(chunks: list[dict[str, Any]], repo_name: str) -> list[dict[str, Any]]:
    paths = []
    for chunk in chunks:
        paths.extend(chunk.get('file_paths') or [])
    paths = sorted(dict.fromkeys(paths))[:24]
    lines = [{'indent': 0, 'indent_spaces': '', 'name': repo_name, 'type': 'dir'}]
    seen_dirs: set[str] = set()
    for path in paths:
        parts = path.split('/')
        for depth, part in enumerate(parts):
            is_file = depth == len(parts) - 1
            key = '/'.join(parts[: depth + 1])
            if not is_file and key in seen_dirs:
                continue
            if not is_file:
                seen_dirs.add(key)
            badge = None
            lower = part.lower()
            if is_file and any(token in lower for token in ('route', 'page', 'router')):
                badge = {'label': 'route', 'colour': 'green'}
            elif is_file and any(token in lower for token in ('db', 'mongo', 'schema', 'model')):
                badge = {'label': 'data', 'colour': 'red'}
            elif is_file and any(token in lower for token in ('main', 'app', 'index', 'config')):
                badge = {'label': 'key', 'colour': 'yellow'}
            lines.append(
                {
                    'indent': depth + 1,
                    'indent_spaces': '  ' * (depth + 1),
                    'name': part,
                    'type': 'file' if is_file else 'dir',
                    'badge': badge,
                }
            )
    return lines


def _file_cards(chunks: list[dict[str, Any]], synthesis: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    file_reference = _text(synthesis.get('file_reference'))
    for chunk in chunks:
        summary = _sentence(chunk.get('summary'), file_reference or 'This file is part of the application codebase.')
        for path in chunk.get('file_paths') or []:
            dir_part, _, file_name = path.rpartition('/')
            lower = path.lower()
            tags = [{'label': 'Key File', 'highlight': True}]
            if any(token in lower for token in ('test', 'spec')):
                tags = [{'label': 'Test', 'highlight': True}]
            elif any(token in lower for token in ('config', 'settings', '.env')):
                tags = [{'label': 'Config', 'highlight': True}]
            elif any(token in lower for token in ('model', 'schema', 'db', 'mongo')):
                tags = [{'label': 'Data', 'highlight': True}]
            cards.append(
                {
                    'path': path,
                    'dir_part': f'{dir_part}/' if dir_part else '',
                    'file_name': file_name or path,
                    'tags': tags,
                    'description': summary[:650],
                    'meta': {
                        'used_by': 'Application runtime',
                        'depends_on': 'Nearby modules and configured services',
                        'if_broken': 'Related functionality may fail or produce incorrect output.',
                        'safe_to_edit': 'Copy, comments, small refactors after testing',
                    },
                }
            )
    if cards:
        return cards[:18]
    return [
        {
            'path': 'repository',
            'dir_part': '',
            'file_name': 'repository',
            'tags': [{'label': 'Overview', 'highlight': True}],
            'description': _sentence(file_reference, 'The repository was analysed and summarized into this owner manual.'),
            'meta': {
                'used_by': 'Project owner',
                'depends_on': 'Source files',
                'if_broken': 'The manual will lose useful context.',
                'safe_to_edit': 'Documentation and explanations',
            },
        }
    ]


def _with_last(items: list[Any]) -> list[Any]:
    output = []
    for index, item in enumerate(items):
        if isinstance(item, dict):
            copy = dict(item)
            copy['isLast'] = index == len(items) - 1
            output.append(copy)
        else:
            output.append({'value': item, '.': item, 'isLast': index == len(items) - 1})
    return output


def build_manual_data(session: dict[str, Any]) -> dict[str, Any]:
    analysis = session.get('analysis', {})
    synthesis = analysis.get('synthesis') or {}
    chunks = analysis.get('chunks') or []
    stack = session.get('stack') or {}
    source_meta = session.get('source_meta') or {}
    repo_name = analysis.get('repo_name') or source_meta.get('filename') or 'repository'
    repo_name = _text(repo_name).removesuffix('.zip')
    display, main, accent = _repo_display_name(repo_name)
    generated_at = datetime.now(timezone.utc)

    file_cards = _file_cards(chunks, synthesis)
    file_page_count = max(1, math.ceil(len(file_cards) / 3))
    total_pages = 5 + file_page_count

    toc = [
        {'num': '01', 'title': 'Architecture Overview', 'page': 3, 'level': 'chapter', 'isChapter': True},
        {'num': '1.1', 'title': 'Stack and file map', 'page': 3, 'level': 'section', 'isSection': True},
        {'num': '02', 'title': 'File Breakdowns', 'page': 4, 'level': 'chapter', 'isChapter': True},
        {'num': '03', 'title': 'Maintenance Guide', 'page': 4 + file_page_count, 'level': 'chapter', 'isChapter': True},
        {'num': '04', 'title': 'Concept Glossary', 'page': 5 + file_page_count, 'level': 'chapter', 'isChapter': True},
    ]

    maintenance_text = _sentence(
        synthesis.get('maintenance_guide'),
        'Keep dependencies current, test changes before deployment, and treat configuration and data-access files carefully.',
    )
    glossary_text = _sentence(
        synthesis.get('concept_glossary'),
        'Important project concepts are explained in plain English throughout this manual.',
    )

    return {
        'META': {
            'repo_name': repo_name,
            'repo_name_display': display,
            'repo_name_main': main,
            'repo_name_accent': accent,
            'repo_url': _text(source_meta.get('url'), 'Uploaded ZIP'),
            'branch': _text(source_meta.get('branch'), 'main'),
            'generated_at': generated_at.strftime('%Y-%m-%d'),
            'generated_at_display': generated_at.strftime('%d %b %Y'),
            'stack_summary': _stack_summary(stack),
            'app_type': _sentence(synthesis.get('app_type'), 'Software Project'),
            'file_count': source_meta.get('file_count') or len(file_cards),
            'version': '1.0.0',
            'total_pages': total_pages,
        },
        'TOC': toc,
        'ARCHITECTURE': {
            'stack_badges': _stack_badges(stack),
            'file_tree': _file_tree(chunks, repo_name),
            'layers': _with_last(
                [
                    {'label': 'Source', 'name': 'Repository', 'items': ['Files are ingested from URL or ZIP', 'Text files are filtered for analysis']},
                    {'label': 'Analysis', 'name': 'CodeReceipt API', 'items': ['Stack detection', 'Plain-English code explanation', 'Manual synthesis']},
                    {'label': 'Output', 'name': 'Owner Manual', 'items': ['Paginated HTML template', 'Local PDF rendering', 'Downloadable artifact']},
                ]
            ),
            'plain_english_summary': _sentence(
                synthesis.get('architecture_overview') or synthesis.get('what_you_built'),
                'This project is organized as a software application with source files, configuration, and supporting services. CodeReceipt reads those parts and turns them into an owner manual.',
            ),
        },
        'FILE_PAGES': [
            {
                'page_number': f'{4 + index:02d}',
                'FILES': page,
            }
            for index, page in enumerate([file_cards[i : i + 3] for i in range(0, len(file_cards), 3)] or [file_cards])
        ],
        'MAINTENANCE_PAGE_NUMBER': f'{4 + file_page_count:02d}',
        'GLOSSARY_PAGE_NUMBER': f'{5 + file_page_count:02d}',
        'MAINTENANCE': {
            'how_to_add_page': {
                'intro': maintenance_text,
                'code_label': '// safe-change workflow',
                'code_lines': [
                    html.escape('1. Make the smallest change that solves the problem.'),
                    html.escape('2. Run the app locally and verify the affected flow.'),
                    html.escape('3. Check logs and error states before deploying.'),
                ],
            },
            'service_schedule': [
                {'area': 'dependencies', 'issue': 'Packages can become outdated.', 'action': 'Review and update on a regular schedule.', 'priority': 'med'},
                {'area': 'configuration', 'issue': 'Secrets and URLs vary by environment.', 'action': 'Keep real values in .env only.', 'priority': 'high'},
                {'area': 'tests', 'issue': 'Changes can break existing flows.', 'action': 'Add focused checks around critical behavior.', 'priority': 'med'},
            ],
            'do_not_touch': [
                {'name': 'Secrets', 'reason': 'Never commit API keys, passwords, or database credentials.'},
                {'name': 'Data access', 'reason': 'Small mistakes can break reads, writes, or exports.'},
            ],
            'safe_to_edit': _with_last(['Documentation', 'UI copy', 'Styling', 'Small isolated helpers']),
        },
        'GLOSSARY': [
            {'term': 'Repository', 'tag': 'Source Code', 'definition': 'The folder of files that make up the application.'},
            {'term': 'API', 'tag': 'Backend', 'definition': 'A route that receives requests and returns data or files.'},
            {'term': 'Environment Variable', 'tag': 'Configuration', 'definition': 'A value like a key or URL that changes between local and production environments.'},
            {'term': 'Dependency', 'tag': 'Packages', 'definition': 'External code the project relies on to run.'},
            {'term': 'Maintenance', 'tag': 'Ownership', 'definition': html.escape(glossary_text)},
        ],
    }


def render_manual_html(session: dict[str, Any]) -> str:
    template = _strip_template_comments(TEMPLATE_PATH.read_text())
    data = build_manual_data(session)
    file_pages_html = []
    file_page_template = _extract_file_page_template(template)
    for file_page in data['FILE_PAGES']:
        page_data = dict(data)
        page_data['FILES'] = file_page['FILES']
        page_data['FILE_PAGE_NUMBER'] = file_page['page_number']
        file_pages_html.append(chevron.render(file_page_template, page_data))
    template = _replace_file_page_template(template, '\n'.join(file_pages_html))
    return chevron.render(template, data)


def _strip_template_comments(template: str) -> str:
    return re.sub(r'<!--.*?-->', '', template, flags=re.DOTALL)


def _extract_file_page_template(template: str) -> str:
    start = template.index('<div class="page" id="page-files">')
    end = template.index('<div class="page" id="page-maintenance">', start)
    return template[start:end]


def _replace_file_page_template(template: str, replacement: str) -> str:
    start = template.index('<div class="page" id="page-files">')
    end = template.index('<div class="page" id="page-maintenance">', start)
    return template[:start] + replacement + '\n' + template[end:]


async def build_pdf_bytes(session: dict[str, Any]) -> bytes:
    html_string = render_manual_html(session)
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(args=['--no-sandbox', '--disable-setuid-sandbox'])
            page = await browser.new_page(viewport={'width': 794, 'height': 1123})
            await page.set_content(html_string, wait_until='networkidle')
            pdf_bytes = await page.pdf(
                format='A4',
                print_background=True,
                margin={'top': '0', 'right': '0', 'bottom': '0', 'left': '0'},
                prefer_css_page_size=True,
            )
            await browser.close()
            return pdf_bytes
    except PlaywrightError as exc:
        raise PdfRenderError(
            'PDF rendering failed in headless Chromium. Ensure Playwright dependencies are installed and Chromium can run in no-sandbox mode.'
        ) from exc
