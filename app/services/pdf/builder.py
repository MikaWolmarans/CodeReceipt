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

from app.services.pdf.sanitise import (
    safe_badge,
    safe_confidence,
    safe_list,
    safe_paragraph,
    safe_prompt,
    safe_risk,
    safe_text,
)


class PdfRenderError(Exception):
    pass


TEMPLATE_PATH = Path(__file__).parent / 'template.html'

_FALLBACK = 'Not confidently detected.'


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _strip_markdown(text: str) -> str:
    """Remove common markdown formatting so descriptions render as plain text."""
    text = re.sub(r'#{1,6}\s*', '', text)
    text = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', text)
    text = re.sub(r'`{1,3}(.+?)`{1,3}', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _t(value: Any, fallback: str = '') -> str:
    if value is None:
        return fallback
    return str(value).strip() or fallback


def _sentence(value: Any, fallback: str) -> str:
    return _t(value) or fallback


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
        items.extend(_t(v) for v in values[:3] if _t(v))
    return ' · '.join(dict.fromkeys(items)) or 'Software Project'


def _stack_badges(stack: dict[str, Any]) -> list[dict[str, Any]]:
    badges: list[dict[str, Any]] = []
    for key in ('frameworks', 'languages', 'databases', 'third_parties'):
        for value in stack.get(key) or []:
            name = _t(value)
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
            if is_file and any(t in lower for t in ('route', 'page', 'router')):
                badge = {'label': 'route', 'colour': 'green'}
            elif is_file and any(t in lower for t in ('db', 'mongo', 'schema', 'model')):
                badge = {'label': 'data', 'colour': 'red'}
            elif is_file and any(t in lower for t in ('main', 'app', 'index', 'config')):
                badge = {'label': 'key', 'colour': 'yellow'}
            lines.append({
                'indent': depth + 1,
                'indent_spaces': '  ' * (depth + 1),
                'name': part,
                'type': 'file' if is_file else 'dir',
                'badge': badge,
            })
    return lines


def _file_cards(chunks: list[dict[str, Any]], synthesis: dict[str, Any]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    fallback_desc = safe_text(synthesis.get('file_reference')) or 'Part of the application codebase.'
    for chunk in chunks:
        file_summaries: dict[str, str] = chunk.get('file_summaries') or {}
        chunk_summary = safe_text(chunk.get('summary')) or fallback_desc
        for path in chunk.get('file_paths') or []:
            raw = (
                file_summaries.get(path)
                or file_summaries.get(path.split('/')[-1])
                or chunk_summary
                or fallback_desc
            )
            description = safe_text(_strip_markdown(_sentence(raw, fallback_desc)), max_len=320)
            dir_part, _, file_name = path.rpartition('/')
            lower = path.lower()
            tag_label = 'Key File'
            if any(t in lower for t in ('test', 'spec')):
                tag_label = 'Test'
            elif any(t in lower for t in ('config', 'settings', '.env')):
                tag_label = 'Config'
            elif any(t in lower for t in ('model', 'schema', 'db', 'mongo')):
                tag_label = 'Data'
            cards.append({
                'path': path,
                'dir_part': f'{dir_part}/' if dir_part else '',
                'file_name': file_name or path,
                'tags': [{'label': tag_label, 'highlight': True}],
                'description': description,
                'meta': {
                    'used_by': _FALLBACK,
                    'depends_on': _FALLBACK,
                    'if_broken': _FALLBACK,
                    'safe_to_edit': _FALLBACK,
                },
            })
    if cards:
        return cards[:18]
    return [{
        'path': 'repository',
        'dir_part': '',
        'file_name': 'repository',
        'tags': [{'label': 'Overview', 'highlight': True}],
        'description': fallback_desc,
        'meta': {
            'used_by': _FALLBACK,
            'depends_on': _FALLBACK,
            'if_broken': _FALLBACK,
            'safe_to_edit': _FALLBACK,
        },
    }]


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


def _checklist(items: list[str]) -> list[dict[str, str]]:
    return [{'text': safe_text(item)} for item in items if item]


# ─────────────────────────────────────────────────────────────
# Section builders
# ─────────────────────────────────────────────────────────────

def _build_quick_start(synthesis: dict[str, Any]) -> dict[str, str]:
    qs = synthesis.get('owner_quick_start') or {}
    if not isinstance(qs, dict):
        qs = {}
    return {
        'what_it_does': safe_paragraph(qs.get('what_it_does') or synthesis.get('what_you_built'), 'This project could not be summarised cleanly from the current scan.'),
        'who_uses_it': safe_text(qs.get('who_uses_it'), _FALLBACK),
        'primary_flow': safe_paragraph(qs.get('primary_flow'), _FALLBACK),
        'main_parts': safe_paragraph(qs.get('main_parts'), _FALLBACK),
        'before_touching': safe_paragraph(qs.get('before_touching'), 'Understand which files handle data and authentication before making changes.'),
    }


def _build_hood(synthesis: dict[str, Any]) -> dict[str, str]:
    return {
        'frontend_desc': safe_paragraph(synthesis.get('frontend_desc'), _FALLBACK),
        'backend_desc': safe_paragraph(synthesis.get('backend_desc'), _FALLBACK),
        'database_desc': safe_paragraph(synthesis.get('database_desc'), _FALLBACK),
        'auth_desc': safe_paragraph(synthesis.get('auth_desc'), _FALLBACK),
        'apis_desc': safe_paragraph(synthesis.get('apis_desc'), _FALLBACK),
        'hosting_desc': safe_paragraph(synthesis.get('hosting_desc'), _FALLBACK),
        'external_desc': safe_paragraph(synthesis.get('external_services_desc'), _FALLBACK),
        'system_flow': safe_text(synthesis.get('system_flow'), 'User → Frontend → Backend → Database'),
    }


def _build_key_systems(synthesis: dict[str, Any]) -> list[dict[str, Any]]:
    raw = synthesis.get('key_systems') or []
    if not isinstance(raw, list):
        return []
    result = []
    for s in raw[:6]:
        if not isinstance(s, dict):
            continue
        result.append({
            'name': safe_text(s.get('name'), 'System'),
            'what_it_does': safe_paragraph(s.get('what_it_does'), _FALLBACK),
            'main_files': safe_text(s.get('main_files'), _FALLBACK),
            'depends_on': safe_text(s.get('depends_on'), _FALLBACK),
            'if_it_breaks': safe_text(s.get('if_it_breaks'), _FALLBACK),
            'safe_edit': safe_text(s.get('safe_edit'), _FALLBACK),
            'risk_level': safe_risk(s.get('risk_level')),
        })
    return result


def _build_safe_touch(synthesis: dict[str, Any]) -> dict[str, list[dict]]:
    def zone(key: str, defaults: list[str]) -> list[dict]:
        items = synthesis.get(key)
        lst = safe_list(items) if items else defaults
        return [{'text': t} for t in lst[:8]]

    return {
        'green': zone('safe_green', ['Documentation and README', 'Static text and labels', 'Styling and CSS', 'Comments']),
        'yellow': zone('safe_yellow', ['UI components', 'Form validation', 'Frontend logic', 'Email templates']),
        'orange': zone('safe_orange', ['API route handlers', 'Database reads and writes', 'Deployment config', 'Background jobs']),
        'red': zone('safe_red', ['Authentication and session logic', 'Payment processing', 'Database migrations', 'Production secrets', 'Permissions and access control']),
    }


def _build_warning_lights() -> list[dict[str, str]]:
    """Standard software warning lights — applicable to most apps."""
    return [
        {'symptom': '500 Server Error', 'meaning': 'A backend route or server process crashed.', 'first_check': 'Server logs and recent code changes.', 'risk': 'high'},
        {'symptom': 'Blank Page', 'meaning': 'The frontend failed to load or a JS error blocked rendering.', 'first_check': 'Browser console errors and network requests.', 'risk': 'high'},
        {'symptom': 'Login Failing', 'meaning': 'Auth service, session config, or credentials are broken.', 'first_check': 'Auth provider logs and environment variables.', 'risk': 'critical'},
        {'symptom': 'Database Error', 'meaning': 'The app cannot connect to or query the database.', 'first_check': 'Database URL, connection limits, and migration status.', 'risk': 'critical'},
        {'symptom': 'Build Failing', 'meaning': 'A dependency, type error, or config issue is blocking the build.', 'first_check': 'Build logs and recently changed files.', 'risk': 'high'},
        {'symptom': 'Emails Not Sending', 'meaning': 'Email provider credentials are missing or limits are reached.', 'first_check': 'Email provider dashboard and API key environment variable.', 'risk': 'med'},
        {'symptom': 'Missing Env Variable', 'meaning': 'A required environment variable is not set in the deployment.', 'first_check': 'Deployment environment settings and .env.example.', 'risk': 'high'},
        {'symptom': 'API Limit Reached', 'meaning': 'An external service has hit its usage quota.', 'first_check': 'Third-party provider dashboard and usage logs.', 'risk': 'med'},
        {'symptom': 'Deployment Failed', 'meaning': 'The hosting platform rejected the latest deploy.', 'first_check': 'Hosting platform logs and build command output.', 'risk': 'high'},
    ]


def _build_running_costs(synthesis: dict[str, Any], stack: dict[str, Any]) -> list[dict[str, str]]:
    raw = synthesis.get('running_costs') or []
    result = []
    if isinstance(raw, list):
        for item in raw[:8]:
            if not isinstance(item, dict):
                continue
            result.append({
                'service': safe_text(item.get('service'), 'Service'),
                'what_it_powers': safe_text(item.get('what_it_powers'), _FALLBACK),
                'what_to_monitor': safe_text(item.get('what_to_monitor'), _FALLBACK),
                'if_limits_reached': safe_text(item.get('if_limits_reached'), _FALLBACK),
                'cost_risk': safe_risk(item.get('cost_risk')),
            })
    return result


def _build_env_vars(synthesis: dict[str, Any]) -> list[dict[str, Any]]:
    raw = synthesis.get('env_vars') or []
    result = []
    if isinstance(raw, list):
        for item in raw[:12]:
            if not isinstance(item, dict):
                continue
            result.append({
                'name': safe_text(item.get('name'), 'UNKNOWN_VAR'),
                'purpose': safe_text(item.get('purpose'), _FALLBACK),
                'required': bool(item.get('required', True)),
                'is_secret': bool(item.get('is_secret', False)),
                'risk_level': safe_risk(item.get('risk_level')),
                'if_missing': safe_text(item.get('if_missing'), _FALLBACK),
                'required_label': 'Required' if item.get('required', True) else 'Optional',
                'secret_label': 'Secret' if item.get('is_secret', False) else 'Public',
            })
    return result


def _build_service_schedule() -> dict[str, list[dict]]:
    return {
        'pre_deploy': _checklist([
            'Run the build and confirm it passes',
            'Test the main user login flow',
            'Check all required environment variables are set',
            'Test the primary user action end-to-end',
            'Check browser console for errors',
            'Review server logs for warnings',
        ]),
        'weekly': _checklist([
            'Check hosting logs for errors and failed requests',
            'Check API usage and remaining quota',
            'Check email delivery rates',
            'Review any user-reported issues',
        ]),
        'monthly': _checklist([
            'Review and update package dependencies',
            'Check billing and usage costs',
            'Verify database backups are running',
            'Check domain and SSL certificate expiry',
            'Generate a fresh CodeReceipt scan',
        ]),
        'before_changes': _checklist([
            'Save the current manual before major changes',
            'Back up the database',
            'Generate an AI handoff prompt',
            'Test changes in a staging environment if available',
            'Compare deployment logs before and after',
        ]),
    }


def _build_risk_register(synthesis: dict[str, Any]) -> list[dict[str, str]]:
    raw = synthesis.get('risk_register') or []
    result = []
    if isinstance(raw, list):
        for item in raw[:8]:
            if not isinstance(item, dict):
                continue
            result.append({
                'area': safe_text(item.get('area'), 'Risk Area'),
                'severity': safe_risk(item.get('severity')),
                'why_it_matters': safe_paragraph(item.get('why_it_matters'), _FALLBACK),
                'where_to_inspect': safe_text(item.get('where_to_inspect'), _FALLBACK),
                'suggested_action': safe_paragraph(item.get('suggested_action'), _FALLBACK),
            })
    if not result:
        # Default risk register
        result = [
            {'area': 'Environment secrets', 'severity': 'high', 'why_it_matters': 'Missing or exposed secrets can break production or expose sensitive services.', 'where_to_inspect': '.env references and deployment environment settings.', 'suggested_action': 'Confirm required variables are set in production and never committed to Git.'},
            {'area': 'Dependency security', 'severity': 'medium', 'why_it_matters': 'Outdated packages may contain known security vulnerabilities.', 'where_to_inspect': 'package.json, requirements.txt, or equivalent dependency files.', 'suggested_action': 'Run a dependency audit and update packages on a regular schedule.'},
            {'area': 'Missing tests', 'severity': 'medium', 'why_it_matters': 'Changes may break existing behaviour without any automated detection.', 'where_to_inspect': 'Test directories and CI configuration.', 'suggested_action': 'Add focused tests around the most critical user-facing flows.'},
        ]
    return result


def _build_troubleshooting() -> list[dict[str, Any]]:
    return [
        {'scenario': 'App will not start', 'steps': _checklist(['Check that dependencies installed successfully.', 'Confirm required environment variables are present and correctly spelled.', 'Check for syntax errors in recently changed files.', 'Review the startup logs for the first error message.']), 'when_to_escalate': 'If the error mentions missing modules, failed migrations, or build tool failures.'},
        {'scenario': 'Build fails', 'steps': _checklist(['Read the first error in the build log carefully.', 'Check recently changed files for syntax or import errors.', 'Confirm all required dependencies are in the package file.']), 'when_to_escalate': 'If the error involves native extensions, version conflicts, or platform-specific tools.'},
        {'scenario': 'Login does not work', 'steps': _checklist(['Check auth provider credentials in environment settings.', 'Verify the auth callback URL matches the deployment domain.', 'Check session or cookie configuration for the environment.']), 'when_to_escalate': 'If users report being locked out of production — treat as a critical incident.'},
        {'scenario': 'Database error', 'steps': _checklist(['Check the DATABASE_URL environment variable is set correctly.', 'Confirm the database service is running and reachable.', 'Check for pending migrations that may not have run.']), 'when_to_escalate': 'If data may be corrupted or migration errors are present — do not attempt manual fixes.'},
        {'scenario': 'Emails not sending', 'steps': _checklist(['Check the email provider API key environment variable.', 'Verify the sender domain is verified with the email provider.', 'Check the provider dashboard for delivery logs and errors.']), 'when_to_escalate': 'If the provider account is suspended or domain is blacklisted.'},
    ]


def _build_ai_handoff(synthesis: dict[str, Any], stack: dict[str, Any]) -> dict[str, str]:
    summary = safe_paragraph(synthesis.get('ai_handoff_context') or synthesis.get('what_you_built'), 'This is an existing software project.')
    systems = safe_text(
        ', '.join(s['name'] for s in _build_key_systems(synthesis)) or synthesis.get('architecture_overview', ''),
        _FALLBACK,
    )
    stack_label = _stack_summary(stack)
    safe_feature = (
        f'You are working on an existing project: {summary} '
        f'Stack: {stack_label}. '
        'Preserve the current architecture. Do not rewrite unrelated files. '
        'Before making changes, list which files you will touch and why. '
        'Keep changes small and testable. '
        'Do not change auth or session logic unless requested. '
        'Do not modify database schema without explaining migration impact.'
    )
    bug_fix = (
        f'You are fixing a bug in an existing project: {summary} '
        'Identify the root cause before making any changes. '
        'Do not change files unrelated to the reported bug. '
        'Explain what is broken and why before proposing a fix. '
        'Test the fix against the original failure scenario.'
    )
    return {
        'project_summary': summary,
        'stack_label': stack_label,
        'key_systems_text': systems,
        'safe_feature_prompt': html.escape(safe_feature),
        'bug_fix_prompt': html.escape(bug_fix),
    }


def _build_known_unknowns(synthesis: dict[str, Any]) -> list[dict[str, str]]:
    raw = synthesis.get('known_unknowns') or []
    result = []
    if isinstance(raw, list):
        for item in raw[:8]:
            if not isinstance(item, dict):
                continue
            result.append({
                'item': safe_text(item.get('item'), 'Unknown item'),
                'confidence': safe_text(item.get('confidence'), 'not found'),
                'why_it_matters': safe_text(item.get('why_it_matters'), _FALLBACK),
            })
    if not result:
        result = [
            {'item': 'Hosting provider', 'confidence': 'not found', 'why_it_matters': 'Deployment settings may live outside the repository.'},
            {'item': 'Production environment variables', 'confidence': 'not found', 'why_it_matters': 'Real secret values are not visible in source code.'},
            {'item': 'Runtime behaviour and performance', 'confidence': 'not found', 'why_it_matters': 'Actual usage patterns can only be observed in a running environment.'},
        ]
    return result


def _build_glossary(synthesis: dict[str, Any], stack: dict[str, Any]) -> list[dict[str, str]]:
    raw = synthesis.get('concept_glossary') or []
    result = []
    if isinstance(raw, list):
        for item in raw[:10]:
            if isinstance(item, dict):
                result.append({
                    'term': safe_text(item.get('term'), 'Term'),
                    'tag': safe_text(item.get('tag'), 'Concept'),
                    'definition': safe_paragraph(item.get('definition'), _FALLBACK),
                })
    if not result:
        result = [
            {'term': 'Repository', 'tag': 'Source Code', 'definition': 'The folder of files that make up the application.'},
            {'term': 'API', 'tag': 'Backend', 'definition': 'A route that receives requests and returns data or files.'},
            {'term': 'Environment Variable', 'tag': 'Configuration', 'definition': 'A value like a key or URL that changes between local and production environments.'},
            {'term': 'Dependency', 'tag': 'Packages', 'definition': 'External code the project relies on to run.'},
        ]
    return result


def _build_next_actions(synthesis: dict[str, Any]) -> list[dict[str, str]]:
    raw = synthesis.get('next_actions') or []
    items: list[str] = []
    if isinstance(raw, list):
        items = [safe_text(a) for a in raw[:5] if a]
    if len(items) < 5:
        defaults = [
            'Save this manual with your project files.',
            'Confirm all required environment variables are set in production.',
            'Test the main user flow end-to-end.',
            'Check running costs and usage limits for external services.',
            'Re-scan after your next major feature or dependency update.',
        ]
        items = items + defaults[len(items):]
    return [{'num': f'{i+1:02d}', 'action': a} for i, a in enumerate(items[:5])]


def _build_identity(stack: dict[str, Any], source_meta: dict[str, Any], synthesis: dict[str, Any]) -> dict[str, Any]:
    def _join(lst: list) -> str:
        items = [_t(v) for v in (lst or []) if _t(v)]
        return ', '.join(items) or _FALLBACK

    return {
        'languages': _join(stack.get('languages', [])),
        'frameworks': _join(stack.get('frameworks', [])),
        'databases': _join(stack.get('databases', [])),
        'hosting': safe_text(synthesis.get('hosting_desc') or stack.get('hosting'), _FALLBACK, max_len=60),
        'auth_provider': safe_text(synthesis.get('auth_desc'), _FALLBACK, max_len=80),
        'external_services': _join(stack.get('third_parties', [])),
        'confidence': safe_confidence(synthesis.get('analysis_confidence')),
    }


# ─────────────────────────────────────────────────────────────
# Main data builder
# ─────────────────────────────────────────────────────────────

def build_manual_data(session: dict[str, Any]) -> dict[str, Any]:
    analysis = session.get('analysis', {})
    synthesis = analysis.get('synthesis') or {}
    chunks = analysis.get('chunks') or []
    stack = session.get('stack') or {}
    source_meta = session.get('source_meta') or {}
    repo_name = analysis.get('repo_name') or source_meta.get('filename') or 'repository'
    repo_name = _t(repo_name).removesuffix('.zip')
    display, main, accent = _repo_display_name(repo_name)
    generated_at = datetime.now(timezone.utc)

    file_cards = _file_cards(chunks, synthesis)
    file_page_count = max(1, math.ceil(len(file_cards) / 2))

    # Page numbers
    p_files_start = 7
    p_safe_touch  = p_files_start + file_page_count
    p_warnings    = p_safe_touch + 1
    p_costs       = p_warnings + 1
    p_schedule    = p_costs + 1
    p_risk        = p_schedule + 1
    p_troubleshoot= p_risk + 1
    p_ai_handoff  = p_troubleshoot + 1
    p_unknowns    = p_ai_handoff + 1
    p_glossary    = p_unknowns + 1
    p_actions     = p_glossary + 1
    total_pages   = p_actions

    toc = [
        {'num': '01', 'title': "Owner's Quick Start",     'page': 3,              'isChapter': True},
        {'num': '02', 'title': 'Project Identity Plate',  'page': 4,              'isChapter': True},
        {'num': '03', 'title': 'Under The Hood',          'page': 5,              'isChapter': True},
        {'num': '04', 'title': 'Key Systems Breakdown',   'page': 6,              'isChapter': True},
        {'num': '05', 'title': 'File Breakdown',          'page': p_files_start,  'isChapter': True},
        {'num': '06', 'title': 'Safe To Touch Map',       'page': p_safe_touch,   'isChapter': True},
        {'num': '07', 'title': 'Dashboard Warning Lights','page': p_warnings,     'isChapter': True},
        {'num': '08', 'title': 'Running Costs & Env Vars','page': p_costs,        'isChapter': True},
        {'num': '09', 'title': 'Service Schedule',        'page': p_schedule,     'isChapter': True},
        {'num': '10', 'title': 'Risk Register',           'page': p_risk,         'isChapter': True},
        {'num': '11', 'title': 'Troubleshooting Runbook', 'page': p_troubleshoot, 'isChapter': True},
        {'num': '12', 'title': 'AI Agent Handoff',        'page': p_ai_handoff,   'isChapter': True},
        {'num': '13', 'title': 'Known Unknowns',          'page': p_unknowns,     'isChapter': True},
        {'num': '14', 'title': 'Concept Glossary',        'page': p_glossary,     'isChapter': True},
        {'num': '15', 'title': 'Next 5 Actions',          'page': p_actions,      'isChapter': True},
    ]

    arch_overview = _sentence(
        synthesis.get('architecture_overview') or synthesis.get('what_you_built'),
        'This project is organised as a software application with source files, configuration, and supporting services.',
    )

    key_systems = _build_key_systems(synthesis)
    running_costs = _build_running_costs(synthesis, stack)
    env_vars = _build_env_vars(synthesis)
    risk_register = _build_risk_register(synthesis)
    troubleshooting = _build_troubleshooting()
    ai_handoff = _build_ai_handoff(synthesis, stack)
    service_schedule = _build_service_schedule()

    return {
        'META': {
            'repo_name': repo_name,
            'repo_name_display': display,
            'repo_name_main': main,
            'repo_name_accent': accent,
            'repo_url': _t(source_meta.get('url'), 'Uploaded ZIP'),
            'branch': _t(source_meta.get('branch'), 'main'),
            'generated_at': generated_at.strftime('%Y-%m-%d'),
            'generated_at_display': generated_at.strftime('%d %b %Y'),
            'stack_summary': _stack_summary(stack),
            'app_type': _sentence(synthesis.get('app_type'), 'Software Project'),
            'file_count': source_meta.get('file_count') or len(file_cards),
            'version': '2.0',
            'total_pages': total_pages,
            'confidence': safe_confidence(synthesis.get('analysis_confidence')),
        },
        'TOC': toc,
        'QUICK_START': _build_quick_start(synthesis),
        'IDENTITY': _build_identity(stack, source_meta, synthesis),
        'ARCHITECTURE': {
            'stack_badges': _stack_badges(stack),
            'file_tree': _file_tree(chunks, repo_name),
            'layers': _with_last([
                {'label': 'Source',   'name': 'Repository',    'items': ['Files ingested from URL or ZIP', 'Text files filtered for analysis']},
                {'label': 'Analysis', 'name': 'CodeReceipt',   'items': ['Stack detection', 'Plain-English explanation', 'Manual synthesis']},
                {'label': 'Output',   'name': 'Owner Manual',  'items': ['Paginated HTML template', 'PDF rendering', 'Downloadable artifact']},
            ]),
            'plain_english_summary': arch_overview,
        },
        'HOOD': _build_hood(synthesis),
        'KEY_SYSTEMS': key_systems,
        'has_key_systems': bool(key_systems),
        'FILE_PAGES': [
            {'page_number': f'{p_files_start + index:02d}', 'FILES': page}
            for index, page in enumerate([file_cards[i: i + 2] for i in range(0, len(file_cards), 2)] or [file_cards])
        ],
        'SAFE_TOUCH': _build_safe_touch(synthesis),
        'WARNINGS': _build_warning_lights(),
        'RUNNING_COSTS': running_costs,
        'has_running_costs': bool(running_costs),
        'ENV_VARS': env_vars,
        'has_env_vars': bool(env_vars),
        'SERVICE_SCHEDULE': service_schedule,
        'RISK_REGISTER': risk_register,
        'TROUBLESHOOTING': troubleshooting,
        'AI_HANDOFF': ai_handoff,
        'KNOWN_UNKNOWNS': _build_known_unknowns(synthesis),
        'GLOSSARY': _build_glossary(synthesis, stack),
        'NEXT_ACTIONS': _build_next_actions(synthesis),
        # Page number tokens for footer spans
        'PAGE_QUICK_START':  '03',
        'PAGE_IDENTITY':     '04',
        'PAGE_HOOD':         '05',
        'PAGE_SYSTEMS':      '06',
        'PAGE_SAFE_TOUCH':   f'{p_safe_touch:02d}',
        'PAGE_WARNINGS':     f'{p_warnings:02d}',
        'PAGE_COSTS':        f'{p_costs:02d}',
        'PAGE_SCHEDULE':     f'{p_schedule:02d}',
        'PAGE_RISK':         f'{p_risk:02d}',
        'PAGE_TROUBLESHOOT': f'{p_troubleshoot:02d}',
        'PAGE_AI_HANDOFF':   f'{p_ai_handoff:02d}',
        'PAGE_UNKNOWNS':     f'{p_unknowns:02d}',
        'PAGE_GLOSSARY':     f'{p_glossary:02d}',
        'PAGE_ACTIONS':      f'{p_actions:02d}',
    }


# ─────────────────────────────────────────────────────────────
# Template rendering
# ─────────────────────────────────────────────────────────────

def _strip_template_comments(template: str) -> str:
    return re.sub(r'<!--.*?-->', '', template, flags=re.DOTALL)


def _extract_file_page_template(template: str) -> str:
    start = template.index('<div class="page" id="page-files">')
    end = template.index('<div class="page" id="page-safe-touch">', start)
    return template[start:end]


def _replace_file_page_template(template: str, replacement: str) -> str:
    start = template.index('<div class="page" id="page-files">')
    end = template.index('<div class="page" id="page-safe-touch">', start)
    return template[:start] + replacement + '\n' + template[end:]


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
        raise PdfRenderError(f'Playwright error: {exc}') from exc
    except Exception as exc:
        raise PdfRenderError(f'Unexpected PDF error ({type(exc).__name__}): {exc}') from exc
