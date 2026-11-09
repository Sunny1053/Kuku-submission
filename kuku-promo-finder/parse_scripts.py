"""Parse Kuku timestamped screenplays using only the Python standard library."""

import argparse
from collections import Counter
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re


TIME = r"\d{2,}:\d{2}\.\d{1,3}"
EVENT = re.compile(
    rf"\*\*(?P<label>.+):\*\*\n"
    rf"Start: \((?P<start>{TIME})\) \| End: \((?P<end>{TIME})\)\n"
    r"(?P<text>[\s\S]+)"
)
SCENE = re.compile(
    rf"SCENE (?P<number>\d+)\nScene heading: (?P<heading>[^\n]+)\n"
    rf"Scene start: (?P<start>{TIME})\nScene end: (?P<end>{TIME})",
    re.IGNORECASE,
)


def milliseconds(timestamp):
    minutes, seconds = timestamp.split(":")
    if not 0 <= Decimal(seconds) < 60:
        raise ValueError(f"Invalid seconds in timestamp {timestamp}")
    return int((int(minutes) * 60 + Decimal(seconds)) * 1000)


def timing(match):
    start, end = match['start'], match['end']
    start_ms, end_ms = milliseconds(start), milliseconds(end)
    if end_ms <= start_ms:
        raise ValueError(f"Non-positive interval {start} to {end}")
    return dict(start=start, end=end, start_ms=start_ms, end_ms=end_ms)


def parse_script(path):
    raw = path.read_bytes()
    text = raw.decode('utf-8-sig').replace('\r\n', '\n').replace('\r', '\n')
    blocks = list(re.finditer(r'\S[\s\S]*?(?=\n[ \t]*\n|\Z)', text))
    episode = None
    scene = None
    started = ended = False
    warnings = []
    for block_match in blocks:
        block = block_match.group().strip()
        line = text.count('\n', 0, block_match.start()) + 1
        if episode is None:
            metadata = re.fullmatch(
                r'EPISODE NUMBER: Episode (\d+)\nEPISODE LOGLINE: ([^\n]+)\n'
                r'CONTINUITY NOTES: ([\s\S]+)', block
            )
            if not metadata:
                raise ValueError(f'Line {line}: expected episode metadata')
            number = int(metadata[1])
            episode = dict(
                id=f'ep{number:03d}', episode_number=number,
                source_file=path.name, source_sha256=hashlib.sha256(raw).hexdigest(),
                logline=metadata[2], continuity_notes=metadata[3], scenes=[],
            )
            continue
        if block == '--- SCRIPT START ---' and not started:
            started = True
            continue
        if block == '--- SCRIPT END ---' and started and not ended:
            ended = True
            continue
        if not started or ended:
            raise ValueError(f'Line {line}: unexpected content outside script')
        scene_match = SCENE.fullmatch(block)
        if scene_match:
            scene_id = f"{episode['id']}-s{int(scene_match['number']):02d}"
            if any(item['id'] == scene_id for item in episode['scenes']):
                raise ValueError(f'Line {line}: duplicate scene {scene_id}')
            scene = dict(id=scene_id, number=int(scene_match['number']),
                         heading=scene_match['heading'], source_line=line,
                         **timing(scene_match), events=[])
            episode['scenes'].append(scene)
            continue
        if block.casefold() == 'actions and dialogue:' and scene is not None:
            continue
        event_match = EVENT.fullmatch(block)
        if event_match and scene is not None:
            label = event_match['label']
            kind = {'CAMERA': 'camera', 'ACTION': 'action', 'SOUND FX': 'sound_fx'}.get(label.upper(), 'dialogue')
            # Keep the original label, including delivery and off-screen cues.
            speaker = label.split(' (', 1)[0] if kind == 'dialogue' else None
            event = dict(id=f"{scene['id']}-b{len(scene['events']) + 1:03d}",
                         kind=kind, label=label, speaker=speaker,
                         text=event_match['text'], source_line=line,
                         **timing(event_match))
            scene['events'].append(event)
            if event['start_ms'] < scene['start_ms'] or event['end_ms'] > scene['end_ms']:
                warnings.append(f"{event['id']} extends outside its scene interval")
            continue
        raise ValueError(f'Line {line}: unrecognized block {block[:100]!r}')
    if episode is None or not ended or not episode['scenes']:
        raise ValueError('Missing metadata, script end, or scenes')
    if any(not item['events'] for item in episode['scenes']):
        raise ValueError('Empty scene')
    event_count = sum(len(item['events']) for item in episode['scenes'])
    source_count = len(re.findall(r'^Start:', text, re.MULTILINE))
    if event_count != source_count:
        raise ValueError(f'Event coverage mismatch: {event_count} parsed, {source_count} in source')
    episode['duration_ms'] = max(
        max(item['end_ms'], max(event['end_ms'] for event in item['events']))
        for item in episode['scenes']
    )
    episode['warnings'] = warnings
    return episode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Folder of episode .txt files')
    parser.add_argument('--output', type=Path, default=Path('local_data/parsed'))
    args = parser.parse_args()
    files = sorted(args.input.glob('*.txt'))
    if not files:
        parser.error(f'No .txt files found in {args.input}')
    episodes, failures = [], []
    ids = set()
    for path in files:
        try:
            episode = parse_script(path)
            if episode['id'] in ids:
                raise ValueError(f"Duplicate episode {episode['id']}")
            ids.add(episode['id'])
            episodes.append(episode)
        except (ValueError, OSError) as error:
            failures.append(dict(source_file=path.name, error=str(error)))
    episodes.sort(key=lambda item: item['episode_number'])
    kinds = Counter(event['kind'] for ep in episodes for scene in ep['scenes'] for event in scene['events'])
    report = dict(files_found=len(files), episodes_parsed=len(episodes),
                  scenes_parsed=sum(len(ep['scenes']) for ep in episodes),
                  events_parsed=sum(kinds.values()), events_by_kind=dict(kinds),
                  warnings=[warning for ep in episodes for warning in ep['warnings']],
                  failures=failures)
    args.output.mkdir(parents=True, exist_ok=True)
    # Atomic replacement prevents a partial write from corrupting either JSON file.
    for name, data in [('episodes.json', dict(schema_version=1, episodes=episodes)),
                       ('parse_report.json', report)]:
        destination = args.output / name
        temporary = destination.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(destination)
    print(json.dumps(report, indent=2))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
