import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from generate_candidates import main
from model_adapter import build_request


class CandidateGenerationTests(unittest.TestCase):
    def test_prompt_preserves_evidence_and_omits_redundant_fields(self):
        beat = dict(id='b1', kind='dialogue', label='Speaker', text='A line',
                    start_ms=100, end_ms=2100, source_line=42, start='00:00.10')
        episode = dict(id='ep001', scenes=[dict(heading='A scene', events=[beat])])
        request = build_request(episode, 'Contract')
        content = json.loads(request['contents'][0]['parts'][0]['text'])
        result = content['scenes'][0]['beats'][0]
        self.assertEqual(result['text'], beat['text'])
        self.assertEqual(result['start_ms'], 100)
        self.assertNotIn('source_line', result)

    def test_batch_retains_partial_results_and_continues_after_failure(self):
        with TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / 'episodes.json'
            source.write_text(json.dumps(dict(schema_version=1, episodes=[
                dict(id='ep001', episode_number=1), dict(id='ep002', episode_number=2)])))

            def fake_run(episode, model, key, output, *args):
                run = output / episode['id']
                run.mkdir(parents=True)
                if episode['episode_number'] == 1:
                    report = dict(valid=1, candidates=2, results=[
                        dict(valid=True, promo=dict(id='good')), dict(valid=False, error='Bad cut')])
                    (run / 'validation.json').write_text(json.dumps(report))
                    return run, dict(status='invalid_candidates')
                return run, dict(status='failed')

            argv = ['generate_candidates.py', '--episodes', str(source), '--episode', '1', '2',
                    '--output', str(folder / 'batches')]
            with patch('sys.argv', argv), patch('generate_candidates.load_settings'), \
                 patch.dict(os.environ, {'GEMINI_API_KEY': 'synthetic', 'GEMINI_MODEL': 'test'}), \
                 patch('generate_candidates.run_episode', side_effect=fake_run) as runner:
                self.assertEqual(main(), 1)
                self.assertEqual(runner.call_count, 2)
            batch = next((folder / 'batches').iterdir())
            manifest = json.loads((batch / 'manifest.json').read_text())
            self.assertEqual(manifest['status'], 'needs_attention')
            self.assertEqual(manifest['runs'][0]['rejected'], 1)
            self.assertEqual(len(json.loads((batch / 'accepted.json').read_text())['promos']), 1)


if __name__ == '__main__':
    unittest.main()
