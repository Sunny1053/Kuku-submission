import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from rank_promos import check_reviews, export_csv, rank_candidates


def review(key, scores=(4, 4, 4), decision='shortlist'):
    return dict(key=key, hook_score=scores[0], clarity_score=scores[1], cliffhanger_score=scores[2],
                decision=decision, rationale='Reason', hook='Hook', cliffhanger='Question',
                why_it_works='Appeal', standalone_context='Context')


def candidate(key, start=0, episode='ep001', warnings=None):
    return dict(key=key, source_reports=['synthetic'], promo=dict(duration_ms=30000, warnings=warnings or [],
                segments=[dict(episode_id=episode, episode_number=1, start_ms=start, end_ms=start + 30000,
                               start='00:00.00', end='00:30.00')]))


class RankingTests(unittest.TestCase):
    def test_bare_review_array_preserves_entries_and_checks_coverage(self):
        item = review('a')
        self.assertEqual(check_reviews([item], {'a'}), {'a': item})
        with self.assertRaises(ValueError):
            check_reviews([item], {'a', 'b'})

    def test_weak_cliffhanger_cannot_be_shortlisted(self):
        result = rank_candidates([candidate('a')], {'a': review('a', (5, 5, 1))})
        self.assertEqual(result[0]['decision'], 'reject')
        self.assertIsNone(result[0]['rank'])

    def test_dedup_preserves_different_episodes_and_best_cut(self):
        items = [candidate('a'), candidate('b', 2000), candidate('c', episode='ep002')]
        reviews = {'a': review('a'), 'b': review('b', (3, 3, 3)), 'c': review('c')}
        rows = {row['key']: row for row in rank_candidates(items, reviews)}
        self.assertEqual(rows['b']['decision'], 'duplicate')
        self.assertEqual(rows['b']['duplicate_of'], 'a')
        self.assertIsNotNone(rows['c']['rank'])

    def test_warnings_require_revision_and_missing_reviews_fail(self):
        row = rank_candidates([candidate('a', warnings=['Cut dialogue'])], {'a': review('a')})[0]
        self.assertEqual(row['decision'], 'revise')
        for payload in [dict(reviews=[]), dict(reviews=[review('a'), review('a')]),
                        dict(reviews=[review('a', (True, 3, 3))])]:
            with self.assertRaises(ValueError):
                check_reviews(payload, ['a'])

    def test_csv_escapes_formula_text(self):
        item = review('a')
        item['hook'] = '=1+1'
        rows = rank_candidates([candidate('a')], {'a': item})
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'result.csv'
            export_csv(path, rows)
            with path.open(encoding='utf-8-sig', newline='') as stream:
                result = next(csv.DictReader(stream))
            self.assertEqual(result['hook'], "'=1+1")
            self.assertEqual(result['duration_seconds'], '30.0')


if __name__ == '__main__':
    unittest.main()
