from app.models.analysis import RepoFile


def pass_one_prompt(files: list[RepoFile]) -> str:
    rendered = []
    for f in files:
        rendered.append(f"### {f.path}\n{f.content[:15000]}")

    paths_json = ', '.join(f'"{f.path}"' for f in files)

    return (
        'You are a technical writer producing a software owner\'s manual. '
        'Return ONLY a valid JSON object — no markdown fences, no preamble, no explanation. '
        'Map each file path to a 1-2 sentence plain-English description. '
        'Write for a non-technical founder. '
        'Do NOT use first-person language, markdown formatting, or bullet points in values. '
        'Each description must state what the file does and what breaks if it is removed.\n\n'
        f'Required keys: {paths_json}\n\n'
        'File contents:\n\n'
        + '\n\n'.join(rendered)
    )


def synthesis_prompt(chunk_outputs: list[str], stack: dict[str, list[str]], options: dict) -> str:
    return (
        'You are producing a structured JSON data object for a software owner\'s manual. '
        'Return ONLY a valid JSON object — no markdown fences, no preamble, no explanation. '
        'Write all values in plain English for a non-technical founder. '
        'Do NOT use first-person language, markdown formatting, or conversational phrasing. '
        f'Stack: {stack}. Options: {options}.\n\n'
        'Required JSON keys:\n'
        '- what_you_built: 1-2 sentence description of the project\n'
        '- app_type: short label e.g. "Web Application", "API Service", "CLI Tool"\n'
        '- architecture_overview: 2-3 sentences on how the system is structured\n'
        '- file_reference: 1 sentence describing the codebase files collectively\n'
        '- maintenance_guide: 2-3 sentences of practical maintenance advice\n'
        '- concept_glossary: 1-2 sentences defining the key technical concepts used\n\n'
        'Chunk analyses:\n'
        + '\n\n'.join(chunk_outputs)
    )
