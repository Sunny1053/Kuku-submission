# Kuku Promo Finder

Problem 1. Rank 20–60 second promo suggestions from timestamped microdrama screenplays.

Requires Python 3.10 or newer. The prototype uses only the Python standard library. Run commands from this directory.

## Offline demo

The bundled Episode 51 is synthetic. Its candidate and review files come from a prior model run on that synthetic episode. Run the four commands below to parse the script, validate the cut, reproduce its ranking, and run the tests. The first three commands produce one ranked cut from 00:00.00 to 00:25.00.

~~~powershell
python parse_scripts.py --input demo/input
python validate_promos.py --candidates demo/candidates.json
python rank_promos.py --inputs local_data/validated_promos.json --reviews demo/reviews.json
python -m unittest -q
~~~

Find the CSV and JSON in the new folder printed by the ranking command.

## Generate on new input

Put timestamped scripts in an input folder. They should follow the format in the synthetic script. Set the two variables below in a local .env file alongside the Python scripts. Use your own API key.

~~~dotenv
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=YOUR_KEY
~~~

~~~powershell
python parse_scripts.py --input path/to/your/scripts
python generate_candidates.py --episode 1 2 3 --provider openrouter --timeout 45
python rank_promos.py --inputs local_data/candidate_batches/BATCH_ID/accepted.json
~~~

Replace the episode numbers and BATCH_ID with the ones in your run. For episodes 1 through 50 in PowerShell, use the commands below after parsing the full pack.

~~~powershell
$kukuEpisodes = 1..50
python generate_candidates.py --episode $kukuEpisodes --provider openrouter --timeout 45
~~~

Read the batch manifest even when generation returns a nonzero exit code. A partially invalid batch retains accepted cuts and reasons for rejection. For targeted retries, provide the affected episode numbers and pass all relevant accepted.json paths to the ranker. Ranking can resume from partial reviews with --resume-reviews. Use --reviews for a complete offline replay and --review-overrides to apply explicit, attributed source checks.

OpenRouter uses Gemini 2.5 Flash Lite with a local $0.90 ceiling and conservative per-call reservations. The ledger persists in local_data/openrouter_budget.json. Keep the ledger when continuing a paid run. A timeout retains the reservation until its charge is known. The model and pricing bounds are isolated in openrouter_adapter.py. The separate candidate adapter in model_adapter.py supports direct Gemini via GEMINI_API_KEY and GEMINI_MODEL with --provider gemini. Ranking uses OpenRouter or saved reviews.

Keep .env, local_data, and the Kuku source pack private. This archive contains synthetic data only. Full-pack outputs are supplied separately for assignment review.
