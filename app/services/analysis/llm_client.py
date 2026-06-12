from __future__ import annotations

import asyncio
import json
import logging

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


def _make_client(settings) -> AsyncOpenAI:
    """Create an AsyncOpenAI client pointed at the configured base URL."""
    return AsyncOpenAI(
        api_key=settings.llm_api_key or 'missing',
        base_url=settings.llm_base_url,
        default_headers={
            'OR-Site-URL': 'https://www.codereceipt.site',
            'OR-App-Name': 'CodeReceipt',
        },
        timeout=120,
    )


class LLMSession:
    """
    Tracks LLM calls within a single analysis run.
    Raises RuntimeError if the per-analysis request cap is exceeded.
    """

    def __init__(self, client: AsyncOpenAI, model: str,
                 max_tokens_per_request: int, max_requests: int) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens_per_request
        self._max_requests = max_requests
        self._call_count = 0

    async def complete(self, prompt: str, temperature: float = 0.2,
                       max_tokens: int | None = None) -> str:
        self._call_count += 1
        if self._call_count > self._max_requests:
            raise RuntimeError(
                f'Analysis aborted: exceeded the maximum of {self._max_requests} '
                'LLM requests per analysis to protect service credits.'
            )

        effective_max_tokens = min(max_tokens or self._max_tokens, self._max_tokens)
        messages = [
            {
                'role': 'system',
                'content': 'You are an expert technical writer focused on plain-English explanations.',
            },
            {'role': 'user', 'content': prompt},
        ]

        # 5xx: retry up to 3 times with a 5 s fixed delay
        for attempt in range(3):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=effective_max_tokens,
                )
                return response.choices[0].message.content

            except Exception as exc:
                status = getattr(exc, 'status_code', None)

                # 402 — insufficient credits; fail immediately, no retry
                if status == 402:
                    logger.critical(
                        'LLM provider returned 402 (insufficient credits). '
                        'Top up credits at openrouter.ai to resume service.'
                    )
                    raise RuntimeError(
                        'Service credit limit reached. Please try again later.'
                    ) from exc

                # 429 — rate limited; honour Retry-After header exactly
                if status == 429:
                    retry_after = _extract_retry_after(exc)
                    logger.warning(
                        'LLM 429 on attempt %d — waiting %.1fs (Retry-After)',
                        attempt + 1, retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue  # retry without consuming an attempt slot

                # Other 4xx — bad request, wrong model, auth failure; fail fast
                if status is not None and 400 <= status < 500:
                    logger.error('LLM %s error (no retry): %s', status, exc)
                    raise RuntimeError(
                        f'LLM request failed with status {status}.'
                    ) from exc

                # 5xx or network error — retry with fixed 5 s delay
                if attempt < 2:
                    logger.warning(
                        'LLM error on attempt %d (%s) — retrying in 5s',
                        attempt + 1, exc,
                    )
                    await asyncio.sleep(5)
                    continue

                # All retries exhausted
                logger.error('LLM request failed after 3 attempts: %s', exc)
                raise RuntimeError('LLM request failed after retries.') from exc

        raise RuntimeError('LLM request failed after retries.')  # unreachable safety net


def _extract_retry_after(exc: Exception) -> float:
    """Pull the Retry-After value (seconds) out of an OpenAI API error."""
    # openai SDK wraps the raw response; try the headers dict first
    response = getattr(exc, 'response', None)
    if response is not None:
        headers = getattr(response, 'headers', {})
        ra = headers.get('retry-after') or headers.get('Retry-After')
        if ra:
            try:
                return float(ra)
            except ValueError:
                pass

    # Fall back to parsing the error body text
    body = str(exc)
    import re
    match = re.search(r'try again in ([\d.]+)s', body)
    if match:
        return float(match.group(1)) + 1.0

    return 10.0  # safe default if no header or body hint


class LLMClient:
    """
    Module-level singleton.  Call `new_session()` for each analysis run to get
    a fresh `LLMSession` that enforces the per-analysis request cap.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._openai_client = _make_client(settings)

        if not settings.llm_api_key:
            logger.error('LLM_API_KEY is not set — LLM calls will fail')
        else:
            key_preview = (
                f'{settings.llm_api_key[:8]}...'
                if len(settings.llm_api_key) > 8
                else '***'
            )
            logger.info(
                'LLMClient initialised — base_url: %s | model: %s | key: %s',
                settings.llm_base_url,
                settings.llm_model,
                key_preview,
            )

    def new_session(self, model_override: str | None = None) -> LLMSession:
        """Return a fresh LLMSession with its own call counter.

        Pass *model_override* to use a different model (e.g. a stronger paid-tier model)
        while reusing the same authenticated OpenAI-compatible client.
        """
        s = self._settings
        return LLMSession(
            client=self._openai_client,
            model=model_override or s.llm_model,
            max_tokens_per_request=s.llm_max_tokens_per_request,
            max_requests=s.llm_max_requests_per_analysis,
        )

    @staticmethod
    def try_parse_json(text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {
                'what_you_built': text,
                'architecture_overview': '',
                'file_reference': '',
                'maintenance_guide': '',
                'concept_glossary': '',
                'quick_reference': '',
            }


llm_client = LLMClient()
