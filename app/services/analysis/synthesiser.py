from __future__ import annotations

import logging
import math

from app.config import get_settings
from app.models.analysis import RepoFile
from app.services.analysis.chunker import chunk_files, _estimate_tokens
from app.services.analysis.llm_client import llm_client
from app.services.analysis.prompts import (
    free_synthesis_prompt,
    pass_one_prompt,
    synthesis_prompt,
)

logger = logging.getLogger(__name__)

_INPUT_COST_PER_TOKEN = 0.15 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 0.60 / 1_000_000
_CHUNK_PROMPT_OVERHEAD = 600
_SYNTHESIS_PROMPT_OVERHEAD = 1_500

# Free tier limits
_FREE_MAX_CHUNKS = 3
_FREE_SYNTHESIS_TOKENS = 1024

# Paid tier limits
_PAID_SYNTHESIS_TOKENS = 4096


def _plan_analysis(
    files: list[RepoFile],
    max_requests: int,
    chunk_output_tokens: int,
    synthesis_output_tokens: int,
):
    max_chunk_calls = max_requests - 1
    if max_chunk_calls < 1:
        raise RuntimeError('LLM_MAX_REQUESTS_PER_ANALYSIS must be at least 2.')

    total_file_tokens = sum(_estimate_tokens(f.content) for f in files)

    default_chunk_size = 6_000
    needed_chunks = math.ceil(total_file_tokens / default_chunk_size) if total_file_tokens else 1
    needed_chunks = max(needed_chunks, 1)

    if needed_chunks <= max_chunk_calls:
        chunk_max_tokens = default_chunk_size
        n_chunks = needed_chunks
    else:
        chunk_max_tokens = math.ceil(total_file_tokens / max_chunk_calls)
        n_chunks = max_chunk_calls

    chunk_input = total_file_tokens + n_chunks * _CHUNK_PROMPT_OVERHEAD
    chunk_output = n_chunks * chunk_output_tokens
    synth_input = n_chunks * chunk_output_tokens + _SYNTHESIS_PROMPT_OVERHEAD
    synth_output = synthesis_output_tokens

    total_input = chunk_input + synth_input
    total_output = chunk_output + synth_output
    estimated_cost = total_input * _INPUT_COST_PER_TOKEN + total_output * _OUTPUT_COST_PER_TOKEN

    return chunk_max_tokens, n_chunks, total_input, total_output, estimated_cost


async def analyse_repository(
    files: list[RepoFile],
    stack: dict[str, list[str]],
    options: dict,
    tier: str = 'free',
) -> tuple[list[dict], dict]:
    settings = get_settings()

    # --- Tier-specific limits ---
    if tier == 'free':
        max_requests = min(settings.llm_max_requests_per_analysis, _FREE_MAX_CHUNKS + 1)
        synthesis_output_tokens = _FREE_SYNTHESIS_TOKENS
        synth_model = settings.llm_model  # cheap model for free tier
        synth_prompt_fn = free_synthesis_prompt
    else:
        max_requests = settings.llm_max_requests_per_analysis
        synthesis_output_tokens = _PAID_SYNTHESIS_TOKENS
        synth_model = settings.paid_synthesis_model or settings.llm_model
        synth_prompt_fn = synthesis_prompt

    chunk_output_tokens = 1024

    chunk_max_tokens, n_chunks, est_input, est_output, est_cost = _plan_analysis(
        files, max_requests, chunk_output_tokens, synthesis_output_tokens
    )

    logger.info(
        'Analysis plan: tier=%s model=%s | %d file(s) → %d chunk(s) + 1 synthesis '
        '(budget: %d requests) | est. tokens in=%d out=%d | est. cost ~$%.4f',
        tier, settings.llm_model, len(files), n_chunks, max_requests,
        est_input, est_output, est_cost,
    )

    if est_cost > 0.50:
        logger.warning(
            'Estimated cost $%.4f exceeds $0.50 threshold for tier=%s.',
            est_cost, tier,
        )

    chunks = chunk_files(files, max_tokens=chunk_max_tokens)
    session = llm_client.new_session()

    chunk_results = []
    for i, chunk in enumerate(chunks):
        prompt = pass_one_prompt(chunk)
        raw = await session.complete(prompt, max_tokens=chunk_output_tokens)
        file_summaries = llm_client.try_parse_json(raw)
        if isinstance(file_summaries, dict) and file_summaries:
            synthesis_text = '\n'.join(f'{k}: {v}' for k, v in file_summaries.items())
        else:
            file_summaries = {}
            synthesis_text = raw
        chunk_results.append({
            'chunk_id': f'chunk-{i + 1}',
            'file_paths': [f.path for f in chunk],
            'summary': synthesis_text,
            'file_summaries': file_summaries,
        })

    synth_prompt = synth_prompt_fn([c['summary'] for c in chunk_results], stack, options)

    # Override synthesis model for paid tier if configured
    if tier != 'free' and settings.paid_synthesis_model:
        paid_session = llm_client.new_session(model_override=settings.paid_synthesis_model)
        synthesis_text = await paid_session.complete(synth_prompt, max_tokens=synthesis_output_tokens)
    else:
        synthesis_text = await session.complete(synth_prompt, max_tokens=synthesis_output_tokens)

    synthesis = llm_client.try_parse_json(synthesis_text)
    return chunk_results, synthesis


async def upgrade_synthesis_to_paid(
    chunk_summaries_text: str,
    stack: dict[str, list[str]],
    options: dict,
) -> dict:
    """Run the full synthesis prompt using pre-stored chunk summaries from a free scan.

    Called from the Stripe webhook handler — avoids re-running the entire analysis pipeline.
    Costs one LLM call instead of N+1.
    """
    settings = get_settings()
    synth_prompt = synthesis_prompt([chunk_summaries_text], stack, options)

    if settings.paid_synthesis_model:
        session = llm_client.new_session(model_override=settings.paid_synthesis_model)
    else:
        session = llm_client.new_session()

    synthesis_text = await session.complete(synth_prompt, max_tokens=_PAID_SYNTHESIS_TOKENS)
    return llm_client.try_parse_json(synthesis_text)
