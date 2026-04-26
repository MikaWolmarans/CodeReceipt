from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'CodeReceipt'

    mongodb_uri: str = Field(alias='MONGODB_URI')
    frontend_url: str = Field(alias='FRONTEND_URL')

    # --- Active LLM configuration ---
    llm_base_url: str = Field(default='https://openrouter.ai/api/v1', alias='LLM_BASE_URL')
    llm_api_key: Optional[str] = Field(default=None, alias='LLM_API_KEY')
    llm_model: str = Field(default='qwen/qwen-2.5-coder-32b-instruct', alias='LLM_MODEL')
    llm_max_tokens_per_request: int = Field(default=4096, alias='LLM_MAX_TOKENS_PER_REQUEST')
    llm_max_requests_per_analysis: int = Field(default=8, alias='LLM_MAX_REQUESTS_PER_ANALYSIS')

    @field_validator('llm_max_tokens_per_request', mode='before')
    @classmethod
    def coerce_max_tokens(cls, v: object) -> object:
        """Treat empty-string env var as absent — fall back to field default."""
        if isinstance(v, str) and v.strip() == '':
            return 4096
        return v

    @field_validator('llm_max_requests_per_analysis', mode='before')
    @classmethod
    def coerce_max_requests(cls, v: object) -> object:
        """Treat empty-string env var as absent — fall back to field default."""
        if isinstance(v, str) and v.strip() == '':
            return 8
        return v

    @field_validator('llm_model', mode='before')
    @classmethod
    def coerce_llm_model(cls, v: object) -> object:
        """Treat empty-string env var as absent — fall back to field default."""
        if isinstance(v, str) and v.strip() == '':
            return 'qwen/qwen-2.5-coder-32b-instruct'
        return v

    @field_validator('llm_base_url', mode='before')
    @classmethod
    def coerce_llm_base_url(cls, v: object) -> object:
        """Treat empty-string env var as absent — fall back to field default."""
        if isinstance(v, str) and v.strip() == '':
            return 'https://openrouter.ai/api/v1'
        return v

    # --- Legacy provider fields (kept for backwards compatibility) ---
    llm_provider: str = Field(default='openrouter', alias='LLM_PROVIDER')
    ollama_base_url: str = Field(default='http://localhost:11434', alias='OLLAMA_BASE_URL')
    ollama_model: str = Field(default='qwen2.5-coder:1.5b', alias='OLLAMA_MODEL')
    openrouter_api_key: Optional[str] = Field(default=None, alias='OPENROUTER_API_KEY')
    openrouter_model: str = Field(default='meta-llama/llama-3.3-70b-instruct:free', alias='OPENROUTER_MODEL')
    openrouter_max_tokens: int = Field(default=4096, alias='OPENROUTER_MAX_TOKENS')
    gemini_api_key: Optional[str] = Field(default=None, alias='GEMINI_API_KEY')
    gemini_model: str = Field(default='gemini-2.0-flash', alias='GEMINI_MODEL')
    groq_api_key: Optional[str] = Field(default=None, alias='GROQ_API_KEY')
    groq_model: str = Field(default='qwen-2.5-coder-32b', alias='GROQ_MODEL')

    github_token: Optional[str] = Field(default=None, alias='GITHUB_TOKEN')

    max_daily_analyses: int = Field(default=100, alias='MAX_DAILY_ANALYSES')
    session_ttl_seconds: int = Field(default=7200, alias='SESSION_TTL_SECONDS')
    max_zip_size_mb: int = Field(default=25, alias='MAX_ZIP_SIZE_MB')
    max_github_repo_size_mb: int = Field(default=15, alias='MAX_GITHUB_REPO_SIZE_MB')

    log_level: str = Field(default='INFO', alias='LOG_LEVEL')

    resend_api_key: Optional[str] = Field(default=None, alias='RESEND_API_KEY')
    from_email: str = Field(default='CodeReceipt <noreply@codereceipt.app>', alias='FROM_EMAIL')
    export_link_ttl_seconds: int = Field(default=86400, alias='EXPORT_LINK_TTL_SECONDS')

    @field_validator('llm_provider')
    @classmethod
    def validate_llm_provider(cls, v: str) -> str:
        allowed = {'ollama', 'openrouter', 'gemini', 'groq'}
        if v.lower() not in allowed:
            raise ValueError(f'LLM_PROVIDER must be one of: {allowed}')
        return v.lower()

    @field_validator('log_level')
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'}
        if v.upper() not in allowed:
            raise ValueError(f'LOG_LEVEL must be one of: {allowed}')
        return v.upper()


def get_settings() -> Settings:
    return Settings()
