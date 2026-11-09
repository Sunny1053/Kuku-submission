"""Synthetic regression cases; no Kuku source content is included."""

from copy import deepcopy
import unittest

from validate_promos import resolve_promo, validate_batch


class PromoValidationTests(unittest.TestCase):
    def setUp(self):
        def beat(identifier, start, end, kind='action'):
            return dict(id=identifier, start_ms=start, end_ms=end,
                        start=f'00:{start / 1000:06.3f}',
                        end=f'00:{end / 1000:06.3f}', kind=kind)
        self.episodes = [dict(id='ep001', episode_number=1, source_file='synthetic.txt',
                             source_sha256='synthetic', duration_ms=70000,
                             scenes=[dict(start_ms=0, end_ms=70000, events=[
                                 beat('opening', 0, 1000), beat('late', 4000, 5000),
                                 beat('ending', 19000, 20000), beat('long', 59000, 60000),
                                 beat('too_long', 60000, 61000),
                                 beat('speech', 19500, 21000, 'dialogue')])])]
        self.candidate = dict(id='promo1', segments=[dict(episode_id='ep001',
                             start_beat_id='opening', end_beat_id='ending')],
                             hook=dict(beat_id='opening', explanation='Opening action'),
                             cliffhanger=dict(beat_id='ending', explanation='Unanswered question'),
                             why_it_works='Visible stakes', standalone_context='Conflict is clear')

    def test_inclusive_duration_and_overlapping_dialogue(self):
        result = resolve_promo(self.candidate, self.episodes)
        self.assertEqual(result['duration_ms'], 20000)
        self.assertIn('interrupts dialogue speech', result['warnings'][0])
        self.assertEqual(result['editorial_review'], 'pending')
        self.candidate['segments'][0]['end_beat_id'] = 'long'
        self.assertEqual(resolve_promo(self.candidate, self.episodes)['duration_ms'], 60000)

    def test_invalid_candidates(self):
        mutations = [
            lambda c: c['segments'][0].update(episode_id='unknown'),
            lambda c: c['segments'][0].update(start_beat_id='unknown'),
            lambda c: c['segments'][0].update(end_beat_id='opening'),
            lambda c: c['segments'][0].update(end_beat_id='too_long'),
            lambda c: c['segments'][0].update(start_beat_id='long'),
            lambda c: c['hook'].update(beat_id='late'),
            lambda c: c['cliffhanger'].update(beat_id='long'),
            lambda c: c.update(why_it_works=' '),
            lambda c: c.update(segments=[{}, {}]),
            lambda c: c.update(hook=None),
            lambda c: c.update(duration_ms=20000),
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)):
                candidate = deepcopy(self.candidate)
                mutation(candidate)
                with self.assertRaises(ValueError):
                    resolve_promo(candidate, self.episodes)

    def test_batch_errors_and_empty_results(self):
        report = validate_batch(dict(schema_version=1, promos=[self.candidate, self.candidate, None]), self.episodes)
        self.assertEqual(report['valid'], 1)
        self.assertEqual(report['candidates'], 3)
        self.assertEqual(validate_batch(dict(schema_version=1, promos=[]), self.episodes)['valid'], 0)


if __name__ == '__main__':
    unittest.main()
