"""Resolve promo selections against parsed scripts and validate their timing."""

import argparse
import json
from pathlib import Path


def require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')
    return value


def require_fields(value, fields, name):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f'{name} requires exactly these fields: {", ".join(fields)}')


def resolve_promo(candidate, episodes):
    """Return a validated result or raise ValueError for an invalid selection.

    Version 1 supports one continuous segment. All times come from source beats.
    Editorial strength and the truth of explanations still need human review.
    """
    require_fields(candidate, ['id', 'segments', 'hook', 'cliffhanger',
                               'why_it_works', 'standalone_context'], 'promo')
    for field in ['id', 'why_it_works', 'standalone_context']:
        require_text(candidate[field], field)
    segments = candidate['segments']
    if not isinstance(segments, list) or len(segments) != 1:
        raise ValueError('Version 1 requires exactly one continuous segment')
    segment = segments[0]
    require_fields(segment, ['episode_id', 'start_beat_id', 'end_beat_id'], 'segment')
    for key, value in segment.items():
        require_text(value, key)
    episode = next((ep for ep in episodes if ep['id'] == segment['episode_id']), None)
    if episode is None:
        raise ValueError('Unknown episode_id')
    events = {event['id']: event for scene in episode['scenes'] for event in scene['events']}
    for field in ['start_beat_id', 'end_beat_id']:
        if segment[field] not in events:
            raise ValueError(f'{field} does not belong to the selected episode')
    opening, closing = events[segment['start_beat_id']], events[segment['end_beat_id']]
    start, end = opening['start_ms'], closing['end_ms']
    duration = end - start
    if closing['start_ms'] < start or end <= start:
        raise ValueError('Reversed segment boundaries')
    if start < 0 or end > episode['duration_ms']:
        raise ValueError('Segment is outside the episode timeline')
    if not 20_000 <= duration <= 60_000:
        raise ValueError('Promo duration must be between 20 and 60 seconds inclusive')
    evidence = {}
    for name in ['hook', 'cliffhanger']:
        claim = candidate[name]
        require_fields(claim, ['beat_id', 'explanation'], name)
        require_text(claim['beat_id'], f'{name}.beat_id')
        require_text(claim['explanation'], f'{name}.explanation')
        beat = events.get(claim['beat_id'])
        if beat is None:
            raise ValueError(f'{name} beat does not belong to the episode')
        if not start <= beat['start_ms'] < beat['end_ms'] <= end:
            raise ValueError(f'{name} evidence must be fully included in the clip')
        evidence[name] = dict(**claim, offset_ms=beat['start_ms'] - start)
    if evidence['hook']['offset_ms'] > 3000:
        raise ValueError('Hook evidence starts after the first three seconds')
    warnings = []
    for event in events.values():
        if event['kind'] == 'dialogue':
            for boundary, timestamp in [('start', start), ('end', end)]:
                if event['start_ms'] < timestamp < event['end_ms']:
                    warnings.append(f"Clip {boundary} interrupts dialogue {event['id']}")
    cliffhanger = events[candidate['cliffhanger']['beat_id']]
    if end - cliffhanger['end_ms'] > 3000:
        warnings.append('Cliffhanger evidence ends more than three seconds before the cut; review trailing content')
    for scene in episode['scenes']:
        for event in scene['events']:
            if event['start_ms'] < end and event['end_ms'] > start:
                if event['start_ms'] < scene['start_ms'] or event['end_ms'] > scene['end_ms']:
                    warnings.append(f"Source scene timing discrepancy at {event['id']}")
    resolved = dict(**segment, episode_number=episode['episode_number'],
                    source_file=episode['source_file'], source_sha256=episode['source_sha256'],
                    start=opening['start'], end=closing['end'], start_ms=start, end_ms=end)
    return dict(id=candidate['id'], segments=[resolved], duration_ms=duration,
                hook=evidence['hook'], cliffhanger=evidence['cliffhanger'],
                why_it_works=candidate['why_it_works'],
                standalone_context=candidate['standalone_context'],
                warnings=warnings, editorial_review='pending')


def validate_batch(payload, episodes):
    require_fields(payload, ['schema_version', 'promos'], 'input')
    if type(payload['schema_version']) is not int or payload['schema_version'] != 1:
        raise ValueError('Unsupported schema_version')
    if not isinstance(payload['promos'], list):
        raise ValueError('promos must be an array')
    results, seen = [], set()
    for index, candidate in enumerate(payload['promos']):
        try:
            promo = resolve_promo(candidate, episodes)
            if promo['id'] in seen:
                raise ValueError('Duplicate promo id')
            seen.add(promo['id'])
            results.append(dict(index=index, valid=True, promo=promo))
        except ValueError as error:
            results.append(dict(index=index, valid=False, error=str(error)))
    return dict(schema_version=1, candidates=len(results),
                valid=sum(item['valid'] for item in results), results=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--episodes', type=Path, default=Path('local_data/parsed/episodes.json'))
    parser.add_argument('--candidates', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('local_data/validated_promos.json'))
    args = parser.parse_args()
    try:
        source = json.loads(args.episodes.read_text(encoding='utf-8-sig'))
        if source['schema_version'] != 1:
            raise ValueError('Unsupported parsed-script schema version')
        candidates = json.loads(args.candidates.read_text(encoding='utf-8-sig'))
        report = validate_batch(candidates, source['episodes'])
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(args.output)
    print(f"Validated {report['valid']} of {report['candidates']} candidates. Report: {args.output}")
    return 0 if report['valid'] == report['candidates'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
