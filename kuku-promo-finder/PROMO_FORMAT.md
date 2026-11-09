# Promo format, version 1

Candidate files contain `schema_version` set to 1 and a `promos` array. An empty array is allowed when no suitable promos are found. Each promo has exactly the following fields.

| Field | Meaning |
| --- | --- |
| id | Unique nonempty promo identifier |
| segments | Ordered array containing one segment in version 1 |
| hook | Object with a source `beat_id` and nonempty `explanation` |
| cliffhanger | Object with a source `beat_id` and nonempty `explanation` |
| why_it_works | Nonempty explanation of the appeal |
| standalone_context | Nonempty explanation of what a first-time viewer can understand from the selected clip |

A segment contains exactly `episode_id`, `start_beat_id`, and `end_beat_id`. Its start is the first beat's start time and its end is the last beat's end time. Source beats are the event IDs produced by the parser. Multiple segments are reserved for a later version and currently produce an error.

The validator resolves the timestamps from the parsed source and returns the episode number, source filename and hash, original start/end strings, integer milliseconds, and total duration. Hook and cliffhanger records also contain their offsets from the start. Unknown or extra candidate fields are rejected to catch mistakes and avoid relying on model-generated timestamps.

## Automatic rules

- Episode and all referenced beats must exist and belong together.
- Boundaries must be ordered, within the episode, and produce 20–60 seconds inclusive.
- Hook and cliffhanger evidence must be entirely included in the cut.
- The hook evidence must start within the first 3 seconds, inclusive. Its start time alone does not establish when a line actually becomes compelling.
- Missing explanations, malformed objects, and duplicate promo IDs are rejected.
- A cut through any overlapping dialogue is flagged for review, even when the selected boundary beat is a camera direction.
- Source scene discrepancies are flagged when they overlap the selected clip.
- Cliffhanger evidence ending over 3 seconds before the cut produces a review warning. This 3-second trailing threshold is a prototype assumption, not an assignment requirement.

## Editorial review

Every valid result starts with `editorial_review` set to `pending`. Review whether the opening actually grabs attention, whether the viewer understands the situation using only this clip, and whether the ending leaves a specific question unanswered. Explanations must match the actual selected content. Automated timing checks cannot prove these qualities. A warning does not invalidate a clip mechanically.

Ranking and review scores will be added in the ranking step. The current output makes no claim about expected advertising performance.
