import json
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        self.max_tokens = settings.openrouter_max_tokens
        key_preview = f'{self.api_key[:8]}...' if self.api_key and len(self.api_key) > 8 else repr(self.api_key)
        logger.info('LLMClient initialised — model: %s | key: %s', self.model, key_preview)

    async def complete(self, prompt: str, temperature: float = 0.2) -> str:
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
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post('https://openrouter.ai/api/v1/chat/completions', headers=headers, json=payload)
            if not resp.is_success:
                logger.error('OpenRouter error %s: %s', resp.status_code, resp.text)
            resp.raise_for_status()
            data = resp.json()
            return data['choices'][0]['message']['content']

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
