"""Generate and validate candidates for selected episodes, retaining run evidence."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from run_model import load_settings, run_episode, save_json
import openrouter_adapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--episodes', type=Path, default=Path('local_data/parsed/episodes.json'))
    parser.add_argument('--episode', type=int, nargs='+', required=True, help='Episode numbers to process')
    parser.add_argument('--output', type=Path, default=Path('local_data/candidate_batches'))
    parser.add_argument('--model')
    parser.add_argument('--provider', choices=['gemini', 'openrouter'])
    parser.add_argument('--thinking-level', choices=['low', 'medium', 'high'], default='low')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        load_settings(Path(__file__).with_name('.env'))
        source = json.loads(args.episodes.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        parser.error('Could not load settings or parsed episodes')
    if source.get('schema_version') != 1:
        parser.error('Unsupported parsed-script version')
    model = args.model or os.environ.get('GEMINI_MODEL')
    key = os.environ.get('GEMINI_API_KEY', '')
    provider = args.provider or ('openrouter' if os.environ.get('LLM_API_KEY') else 'gemini')
    if provider == 'openrouter':
        if os.environ.get('LLM_BASE_URL', '').rstrip('/') != 'https://openrouter.ai/api/v1':
            parser.error('Budgeted adapter requires the OpenRouter API base URL')
        model, key = openrouter_adapter.MODEL, os.environ.get('LLM_API_KEY', '')
    if not args.dry_run and (not model or not key.strip()):
        parser.error('Configure GEMINI_MODEL and GEMINI_API_KEY')
    requested = list(dict.fromkeys(args.episode))
    episodes = {ep['episode_number']: ep for ep in source['episodes']}
    if args.timeout <= 0 or any(number not in episodes for number in requested):
        parser.error('Use a positive timeout and existing episode numbers')
    folder = args.output / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    folder.mkdir(parents=True)
    manifest = dict(dry_run=args.dry_run, requested_episodes=requested, status='running', runs=[])
    save_json(folder / 'manifest.json', manifest)
    accepted = []
    for number in requested:
        run, metadata = run_episode(episodes[number], model, key, folder / 'runs',
                                    args.timeout, args.thinking_level, args.dry_run, provider)
        entry = dict(episode_number=number, run_directory=str(run.relative_to(folder)),
                     status=metadata['status'], accepted=0, rejected=0)
        validation = run / 'validation.json'
        if validation.exists():
            report = json.loads(validation.read_text(encoding='utf-8'))
            entry.update(accepted=report['valid'], rejected=report['candidates'] - report['valid'])
            accepted.extend(dict(run_directory=entry['run_directory'], promo=item['promo'])
                            for item in report['results'] if item['valid'])
        manifest['runs'].append(entry)
        save_json(folder / 'manifest.json', manifest)
        save_json(folder / 'accepted.json', dict(schema_version=1, promos=accepted))
    failed = any(item['status'] != 'validated' for item in manifest['runs'])
    manifest['status'] = 'dry_run' if args.dry_run else ('needs_attention' if failed else 'complete')
    save_json(folder / 'manifest.json', manifest)
    print(f"Batch {manifest['status']}: {len(accepted)} validated candidates. Folder: {folder}")
    return int(failed and not args.dry_run)


if __name__ == '__main__':
    raise SystemExit(main())
