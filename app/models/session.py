from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class SourceMeta(BaseModel):
    url: str | None = None
    filename: str | None = None
    file_count: int = 0
    total_bytes: int = 0


class StackProfile(BaseModel):
    languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    databases: list[str] = Field(default_factory=list)
    third_parties: list[str] = Field(default_factory=list)


class AnalysisOptions(BaseModel):
    architecture_map: bool = True
    maintenance_guide: bool = True
    concept_glossary: bool = True
    inline_code_notes: bool = False


class SessionDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()), alias='_id')
    status: Literal['pending', 'processing', 'complete', 'failed'] = 'pending'
    progress: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_type: Literal['github', 'zip']
    source_meta: SourceMeta = Field(default_factory=SourceMeta)
    stack: StackProfile = Field(default_factory=StackProfile)
    options: AnalysisOptions = Field(default_factory=AnalysisOptions)
    analysis: dict[str, Any] = Field(default_factory=lambda: {'chunks': [], 'synthesis': {}})
    pdf_delivered: bool = False
    error: str | None = None
    notify_email: str | None = None
    # Monetisation
    tier: Literal['free', 'owner_manual', 'workshop'] = 'free'
    paid: bool = False
    paid_at: datetime | None = None
    stripe_checkout_id: str | None = None
    payment_email: str | None = None
    # Cost control
    repo_hash: str | None = None              # SHA256 for cache lookup
    chunk_summaries_text: str | None = None   # Stored for paid synthesis upgrade


class AnalyseResponse(BaseModel):
    session_id: str | None = None
    requires_upgrade: bool = False
    upgrade_reason: str | None = None


class StatusResponse(BaseModel):
    session_id: str
    status: str
    progress: int
    error: str | None = None
