import asyncio

from app.models.analysis import RepoFile
from app.services.analysis.chunker import chunk_files
from app.services.analysis.llm_client import llm_client
from app.services.analysis.prompts import pass_one_prompt, synthesis_prompt


async def analyse_repository(files: list[RepoFile], stack: dict[str, list[str]], options: dict) -> tuple[list[dict], dict]:
    chunks = chunk_files(files)

    async def run_chunk(index: int, chunk: list[RepoFile]) -> dict:
        prompt = pass_one_prompt(chunk)
        summary = await llm_client.complete(prompt)
        return {
            'chunk_id': f'chunk-{index + 1}',
            'file_paths': [f.path for f in chunk],
            'summary': summary,
        }

    chunk_results = await asyncio.gather(*[run_chunk(i, c) for i, c in enumerate(chunks)])

    synth_prompt = synthesis_prompt([c['summary'] for c in chunk_results], stack, options)
    synthesis_text = await llm_client.complete(synth_prompt)
    synthesis = llm_client.try_parse_json(synthesis_text)
    return chunk_results, synthesis
