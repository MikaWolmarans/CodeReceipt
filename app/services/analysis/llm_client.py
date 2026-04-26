import asyncio
import json
import logging
import random

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Max concurrent LLM requests — free tier models rate-limit on bursts
_semaphore = asyncio.Semaphore(2)


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        self.max_tokens = settings.openrouter_max_tokens
        if not self.api_key:
            logger.error('OPENROUTER_API_KEY is not set — LLM calls will fail')
        else:
            key_preview = f'{self.api_key[:8]}...' if len(self.api_key) > 8 else '***'
            logger.info('LLMClient initialised — model: %s | key: %s', self.model, key_preview)

    async def complete(self, prompt: str, temperature: float = 0.2) -> str:
        if not self.api_key:
            raise RuntimeError('OPENROUTER_API_KEY is not configured on this server.')
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': 'You are an expert technical writer focused on plain-English explanations.'},
                {'role': 'user', 'content': prompt},
            ],
            'temperature': temperature,
            'max_tokens': self.max_tokens,
        }
        for attempt in range(4):
            async with _semaphore:
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.post(
                        'https://openrouter.ai/api/v1/chat/completions',
                        headers=headers,
                        json=payload,
                    )
            if resp.status_code == 429:
                wait = (2 ** attempt) + random.uniform(0, 1)  # 1-2s, 2-3s, 4-5s, 8-9s
                logger.warning('OpenRouter 429 on attempt %d — retrying in %.1fs', attempt + 1, wait)
                await asyncio.sleep(wait)
                continue
            if not resp.is_success:
                logger.error('OpenRouter error %s: %s', resp.status_code, resp.text)
            resp.raise_for_status()
            return resp.json()['choices'][0]['message']['content']
        raise RuntimeError('OpenRouter rate limit exceeded after retries.')

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
