from app.models.analysis import RepoFile


def pass_one_prompt(files: list[RepoFile]) -> str:
    rendered = []
    for f in files:
        rendered.append(f"### FILE: {f.path}\n{f.content[:15000]}")

    return (
        'You are writing for a non-technical founder. Explain what these files do in plain English. '
        'Avoid jargon; if a technical term is needed, define it immediately. '
        'For each file or group, include: purpose, key behavior, and what breaks if deleted.\n\n'
        + '\n\n'.join(rendered)
    )


def synthesis_prompt(chunk_outputs: list[str], stack: dict[str, list[str]], options: dict) -> str:
    return (
        'Create a polished owner manual styled like a car user manual for software ownership. '\
        'Use clear headers and friendly but precise tone. '\
        f'Stack clues: {stack}. Options: {options}. '\
        'Output JSON with keys: what_you_built, architecture_overview, file_reference, maintenance_guide, '
        'concept_glossary, quick_reference.\n\nChunk analyses:\n'
        + '\n\n'.join(chunk_outputs)
    )
