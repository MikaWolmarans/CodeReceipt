from app.models.analysis import RepoFile


def _estimate_tokens(text: str) -> int:
    """Rough token count: ~4 chars per token (good enough for budget planning)."""
    return max(1, len(text) // 4)


def chunk_files(files: list[RepoFile], max_tokens: int = 6000) -> list[list[RepoFile]]:
    chunks: list[list[RepoFile]] = []
    current: list[RepoFile] = []
    current_tokens = 0

    for file in files:
        file_tokens = _estimate_tokens(file.content)
        if current and current_tokens + file_tokens > max_tokens:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(file)
        current_tokens += file_tokens
    if current:
        chunks.append(current)
    return chunks
