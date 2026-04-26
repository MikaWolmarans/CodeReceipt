import json

import httpx

from app.config import get_settings


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.openrouter_api_key
        self.model = settings.openrouter_model
        self.max_tokens = settings.openrouter_max_tokens

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
