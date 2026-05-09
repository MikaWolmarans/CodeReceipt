"""
Sanitisation utilities for PDF rendering.

All AI output must pass through these helpers before being placed into the
template.  They prevent raw JSON, [object Object], null, undefined, and
over-long strings from appearing in the final PDF.
"""
from __future__ import annotations

import html
import re
from typing import Any

_FALLBACK_TEXT = 'Not confidently detected.'
_FALLBACK_PARAGRAPH = 'This section could not be generated cleanly from the current scan.'

# Patterns that indicate a raw JSON / Python-repr leak
_LEAK_RE = re.compile(
    r'\[object Object\]'
    r'|"\w[\w\s]*"\s*:\s*[\{\[]'   # "key": { or "key": [
    r"|'\w[\w\s]*'\s*:\s*[\{\[]"   # 'key': {
    r'|\{\s*"[^"]+"\s*:'           # {"key":
    r'|\bNone\b|\bundefined\b'
)


def _looks_like_leak(s: str) -> bool:
    return bool(_LEAK_RE.search(s))


# ─────────────────────────────────────────────
# Core primitives
# ─────────────────────────────────────────────

def safe_text(value: Any, fallback: str = _FALLBACK_TEXT, max_len: int = 0) -> str:
    """Return a clean, HTML-escaped string or *fallback*."""
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return fallback
    s = str(value).strip()
    if not s:
        return fallback
    if _looks_like_leak(s):
        return fallback
    s = re.sub(r'\s+', ' ', s)
    if max_len and len(s) > max_len:
        s = s[:max_len].rstrip() + '…'
    return html.escape(s)


def safe_paragraph(value: Any, fallback: str = _FALLBACK_PARAGRAPH, max_len: int = 600) -> str:
    """Like safe_text but with a longer default cap for paragraph fields."""
    return safe_text(value, fallback, max_len)


def safe_list(value: Any, fallback: str = _FALLBACK_TEXT) -> list[str]:
    """Convert any list-like or comma-separated string to a clean list."""
    if not value:
        return [fallback]
    if isinstance(value, str):
        if _looks_like_leak(value):
            return [fallback]
        items = [safe_text(item.strip()) for item in re.split(r'[;\n]|,\s', value) if item.strip()]
        return items or [fallback]
    if isinstance(value, list):
        items = [safe_text(v) for v in value if v is not None and not isinstance(v, (dict, list))]
        filtered = [i for i in items if i != _FALLBACK_TEXT]
        return filtered if filtered else [fallback]
    return [fallback]


def safe_badge(value: Any) -> str:
    """Short label for a badge — truncated, no HTML escaping needed in badge context."""
    s = safe_text(value, '')
    return s[:40] if s else ''


def safe_risk(value: Any) -> str:
    """Normalise a risk/severity label to one of: low, medium, high, critical, unknown."""
    s = str(value).strip().lower() if value else ''
    if s in ('low', 'medium', 'high', 'critical'):
        return s
    return 'unknown'


def safe_confidence(value: Any) -> str:
    """Normalise a confidence label to one of: high, medium, low."""
    s = str(value).strip().lower() if value else ''
    if s in ('high', 'medium', 'low'):
        return s
    return 'medium'


def safe_prompt(value: Any) -> str:
    """For AI prompt copy-boxes — preserve newlines, strip leaks."""
    if not value or isinstance(value, (dict, list)):
        return ''
    s = str(value).strip()
    if _looks_like_leak(s):
        return ''
    # Replace raw newlines with <br> after escaping
    return html.escape(s).replace('\n', '<br>')
