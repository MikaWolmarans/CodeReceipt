import asyncio
import json
import logging
import random

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Max concurrent LLM requests — free tier models rate-limit on bursts
_semaphore = asyncio.Semaphore(2)

PROVIDER_ENDPOINTS = {
    'openrouter': 'https://openrouter.ai/api/v1/chat/completions',
    'gemini': 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
    'groq': 'https://api.groq.com/openai/v1/chat/completions',
}


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.provider = settings.llm_provider

        if self.provider == 'gemini':
            self.api_key = settings.gemini_api_key
            self.model = settings.gemini_model
            self.max_tokens = 4096
        elif self.provider == 'groq':
            self.api_key = settings.groq_api_key
            self.model = settings.groq_model
            self.max_tokens = 4096
        else:  # openrouter
            self.api_key = settings.openrouter_api_key
            self.model = settings.openrouter_model
            self.max_tokens = settings.openrouter_max_tokens

        self.endpoint = PROVIDER_ENDPOINTS.get(self.provider, PROVIDER_ENDPOINTS['openrouter'])

        if not self.api_key:
            logger.error('%s API key is not set — LLM calls will fail', self.provider.upper())
        else:
            key_preview = f'{self.api_key[:8]}...' if len(self.api_key) > 8 else '***'
            logger.info('LLMClient initialised — provider: %s | model: %s | key: %s',
                        self.provider, self.model, key_preview)

    async def complete(self, prompt: str, temperature: float = 0.2) -> str:
        if not self.api_key:
            raise RuntimeError(f'{self.provider.upper()} API key is not configured on this server.')
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
                    resp = await client.post(self.endpoint, headers=headers, json=payload)
            if resp.status_code == 429:
                wait = (2 ** attempt) + random.uniform(0, 1)
                logger.warning('%s 429 on attempt %d — body: %s — retrying in %.1fs',
                               self.provider, attempt + 1, resp.text, wait)
                await asyncio.sleep(wait)
                continue
            if not resp.is_success:
                logger.error('%s error %s: %s', self.provider, resp.status_code, resp.text)
            resp.raise_for_status()
            return resp.json()['choices'][0]['message']['content']
        raise RuntimeError(f'{self.provider} rate limit exceeded after retries.')

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
