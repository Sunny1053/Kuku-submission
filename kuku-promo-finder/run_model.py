"""Run one episode through Gemini, saving request, raw response, and validation."""

import argparse
from getpass import getpass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from uuid import uuid4

from model_adapter import build_request, extract_candidates, generate
from validate_promos import validate_batch
import openrouter_adapter


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def load_settings(path):
    """Read the two supported settings without logging secrets or overriding env."""
    if not path.exists():
        return
    settings = {}
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not separator or key not in ('GEMINI_API_KEY', 'GEMINI_MODEL', 'LLM_BASE_URL', 'LLM_API_KEY', 'LLM_MODEL'):
            raise ValueError(f'Unsupported .env setting at line {number}')
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'Unclosed .env quote at line {number}')
            value = value[1:-1]
        if key in settings:
            raise ValueError(f'Duplicate .env setting at line {number}')
        settings[key] = value
    for key, value in settings.items():
        os.environ.setdefault(key, value)


def run_episode(episode, model, api_key, output, timeout=300, thinking_level=None, dry_run=False, provider='gemini'):
    contract = Path(__file__).with_name('PROMO_FORMAT.md').read_text(encoding='utf-8')
    body = build_request(episode, contract)
    if thinking_level:
        body['generationConfig']['thinkingConfig'] = dict(thinkingLevel=thinking_level)
    if provider == 'openrouter':
        body = openrouter_adapter.build_body(body)
        model = openrouter_adapter.MODEL
    run = output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    run.mkdir(parents=True)
    save_json(run / 'request.json', body)
    metadata = dict(provider=provider, requested_model=model, episode_id=episode['id'],
                    source_sha256=episode['source_sha256'], dry_run=dry_run,
                    status='prepared', started_at=datetime.now(timezone.utc).isoformat())
    save_json(run / 'run.json', metadata)
    if dry_run:
        print(f'Dry run prepared at {run}. No model request sent.')
        return run, metadata
    started = time.monotonic()
    try:
        if provider == 'openrouter':
            raw = openrouter_adapter.generate(api_key, body, run / 'response.raw.json', timeout)
            extract = openrouter_adapter.extract_candidates
        else:
            raw = generate(model, api_key, body, timeout=timeout)
            extract = extract_candidates
        (run / 'response.raw.json').write_bytes(raw)
        response = json.loads(raw)
        metadata.update(usage=response.get('usageMetadata', {}), returned_model=response.get('modelVersion'))
        candidates, usage, version = extract(raw)
        save_json(run / 'candidates.json', candidates)
        # Restrict evidence to the episode actually supplied to the model.
        report = validate_batch(candidates, [episode])
        save_json(run / 'validation.json', report)
        metadata.update(usage=usage, returned_model=version,
                        status='validated' if report['valid'] == report['candidates'] else 'invalid_candidates')
    except (ValueError, RuntimeError, OSError) as error:
        metadata.update(status='failed', error=str(error))
    metadata['elapsed_seconds'] = round(time.monotonic() - started, 3)
    save_json(run / 'run.json', metadata)
    print(f"Run status: {metadata['status']}. Files: {run}")
    if 'error' in metadata:
        print(metadata['error'])
    return run, metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    try:
        load_settings(Path(__file__).with_name('.env'))
    except (ValueError, OSError):
        parser.error('Could not load .env. Check its two setting names, encoding, and quotes.')
    parser.add_argument('--episode', type=int, default=1)
    parser.add_argument('--provider', choices=['gemini', 'openrouter'], default='openrouter' if os.environ.get('LLM_API_KEY') else 'gemini')
    parser.add_argument('--timeout', type=int, default=120, help='API timeout in seconds')
    parser.add_argument('--thinking-level', choices=['low', 'medium', 'high'], help='For Gemini models supporting thinkingLevel')
    parser.add_argument('--model', default=os.environ.get('GEMINI_MODEL'))
    parser.add_argument('--episodes', type=Path, default=Path('local_data/parsed/episodes.json'))
    parser.add_argument('--output', type=Path, default=Path('local_data/model_runs'))
    parser.add_argument('--dry-run', action='store_true', help='Save the request without calling Gemini')
    parser.add_argument('--prompt-key', action='store_true', help='Enter the API key privately in a terminal')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    api_key = os.environ.get('GEMINI_API_KEY', '')
    if args.provider == 'openrouter':
        if os.environ.get('LLM_BASE_URL', '').rstrip('/') != 'https://openrouter.ai/api/v1':
            parser.error('Budgeted adapter requires the OpenRouter API base URL')
        api_key = os.environ.get('LLM_API_KEY', '')
        args.model = openrouter_adapter.MODEL
    if args.prompt_key and not args.dry_run:
        api_key = getpass('API key (hidden): ')
    if not args.dry_run and (not args.model or not api_key.strip()):
        parser.error('Set GEMINI_API_KEY and GEMINI_MODEL in the environment, or use --model. No request was sent.')
    source = json.loads(args.episodes.read_text(encoding='utf-8-sig'))
    if source.get('schema_version') != 1:
        parser.error('Unsupported parsed episode schema')
    episode = next((ep for ep in source['episodes'] if ep['episode_number'] == args.episode), None)
    if episode is None:
        parser.error('Requested episode was not found')
    _, metadata = run_episode(episode, args.model, api_key, args.output, args.timeout,
                              args.thinking_level, args.dry_run, args.provider)
    return 0 if args.dry_run or metadata['status'] == 'validated' else 1


if __name__ == '__main__':
    raise SystemExit(main())
