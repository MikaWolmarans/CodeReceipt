from __future__ import annotations

from pydantic import BaseModel, Field


class RepoFile(BaseModel):
    path: str
    content: str


class ChunkSummary(BaseModel):
    chunk_id: str
    file_paths: list[str] = Field(default_factory=list)
    summary: str
