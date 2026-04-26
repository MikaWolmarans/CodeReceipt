import logging
import math

from app.config import get_settings
from app.models.analysis import RepoFile
from app.services.analysis.chunker import chunk_files, _estimate_tokens
from app.services.analysis.llm_client import llm_client
from app.services.analysis.prompts import pass_one_prompt, synthesis_prompt

logger = logging.getLogger(__name__)

# Pricing used for the pre-flight cost estimate (USD per token).
# These match openai/gpt-4o-mini on OpenRouter; actual cost varies by model:
#   gpt-4o-mini:              $0.150 / $0.600 per 1M in/out
#   qwen/qwen-2.5-coder-32b:  $0.070 / $0.160 per 1M in/out
# The estimate is intentionally conservative (gpt-4o-mini rates) so it
# never under-reports cost regardless of which model is configured.
_INPUT_COST_PER_TOKEN = 0.15 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 0.60 / 1_000_000

# Overhead tokens added to each chunk call by the prompt template + system message
_CHUNK_PROMPT_OVERHEAD = 600
# Overhead tokens added to the synthesis call (prompt template, stack info, etc.)
_SYNTHESIS_PROMPT_OVERHEAD = 1_500


def _plan_analysis(files: list[RepoFile], max_requests: int, chunk_output_tokens: int, synthesis_output_tokens: int):
    """
    Work out how many chunks the repo needs and whether that fits within
    `max_requests`.  If not, increase the chunk size until it does.

    Returns (chunk_max_tokens, n_chunks, estimated_cost_usd).
    """
    max_chunk_calls = max_requests - 1  # one slot reserved for synthesis
    if max_chunk_calls < 1:
        raise RuntimeError('LLM_MAX_REQUESTS_PER_ANALYSIS must be at least 2.')

    total_file_tokens = sum(_estimate_tokens(f.content) for f in files)

    # Start with the chunker's default and grow if needed
    default_chunk_size = 6_000
    needed_chunks = math.ceil(total_file_tokens / default_chunk_size) if total_file_tokens else 1
    needed_chunks = max(needed_chunks, 1)

    if needed_chunks <= max_chunk_calls:
        chunk_max_tokens = default_chunk_size
        n_chunks = needed_chunks
    else:
        # Scale chunk size up so we stay within budget
        chunk_max_tokens = math.ceil(total_file_tokens / max_chunk_calls)
        n_chunks = max_chunk_calls

    # Rough cost estimate -------------------------------------------------------
    # Input: file tokens per chunk + prompt overhead; output: capped at max_tokens
    chunk_input = total_file_tokens + n_chunks * _CHUNK_PROMPT_OVERHEAD
    chunk_output = n_chunks * chunk_output_tokens
    # Synthesis input: summaries (each ≈ chunk_output_tokens) + overhead
    synth_input = n_chunks * chunk_output_tokens + _SYNTHESIS_PROMPT_OVERHEAD
    synth_output = synthesis_output_tokens

    total_input = chunk_input + synth_input
    total_output = chunk_output + synth_output
    estimated_cost = total_input * _INPUT_COST_PER_TOKEN + total_output * _OUTPUT_COST_PER_TOKEN

    return chunk_max_tokens, n_chunks, total_input, total_output, estimated_cost


async def analyse_repository(files: list[RepoFile], stack: dict[str, list[str]], options: dict) -> tuple[list[dict], dict]:
    settings = get_settings()
    max_requests = settings.llm_max_requests_per_analysis
    chunk_output_tokens = 1024
    synthesis_output_tokens = 2048

    chunk_max_tokens, n_chunks, est_input, est_output, est_cost = _plan_analysis(
        files, max_requests, chunk_output_tokens, synthesis_output_tokens
    )

    logger.info(
        'Analysis plan: model=%s | %d file(s) → %d chunk(s) + 1 synthesis '
        '(budget: %d requests) | est. tokens in=%d out=%d | est. cost ~$%.4f',
        settings.llm_model, len(files), n_chunks, max_requests, est_input, est_output, est_cost,
    )

    if est_cost > 0.50:
        logger.warning(
            'Estimated cost $%.4f exceeds $0.50 threshold — consider reducing '
            'MAX_ZIP_SIZE_MB / MAX_GITHUB_REPO_SIZE_MB or raising '
            'LLM_MAX_REQUESTS_PER_ANALYSIS to allow larger chunks.',
            est_cost,
        )

    chunks = chunk_files(files, max_tokens=chunk_max_tokens)
    session = llm_client.new_session()

    # Process chunks sequentially — avoid burst 429s on rate-limited providers
    chunk_results = []
    for i, chunk in enumerate(chunks):
        prompt = pass_one_prompt(chunk)
        summary = await session.complete(prompt, max_tokens=chunk_output_tokens)
        chunk_results.append({
            'chunk_id': f'chunk-{i + 1}',
            'file_paths': [f.path for f in chunk],
            'summary': summary,
        })

    synth_prompt = synthesis_prompt([c['summary'] for c in chunk_results], stack, options)
    synthesis_text = await session.complete(synth_prompt, max_tokens=synthesis_output_tokens)
    synthesis = llm_client.try_parse_json(synthesis_text)
    return chunk_results, synthesis
