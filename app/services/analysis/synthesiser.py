from app.models.analysis import RepoFile
from app.services.analysis.chunker import chunk_files
from app.services.analysis.llm_client import llm_client
from app.services.analysis.prompts import pass_one_prompt, synthesis_prompt


async def analyse_repository(files: list[RepoFile], stack: dict[str, list[str]], options: dict) -> tuple[list[dict], dict]:
    chunks = chunk_files(files)

    # Process chunks sequentially — free-tier LLMs have very low rate limits
    # and concurrent requests cause immediate 429s that exhaust retries.
    chunk_results = []
    for i, chunk in enumerate(chunks):
        prompt = pass_one_prompt(chunk)
        # 1024 tokens is plenty for a chunk summary and keeps TPM usage low
        summary = await llm_client.complete(prompt, max_tokens=1024)
        chunk_results.append({
            'chunk_id': f'chunk-{i + 1}',
            'file_paths': [f.path for f in chunk],
            'summary': summary,
        })

    synth_prompt = synthesis_prompt([c['summary'] for c in chunk_results], stack, options)
    synthesis_text = await llm_client.complete(synth_prompt, max_tokens=2048)
    synthesis = llm_client.try_parse_json(synthesis_text)
    return chunk_results, synthesis
