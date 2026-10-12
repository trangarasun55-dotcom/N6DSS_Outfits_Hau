# Project guidance

## Architecture

- `data/DatasetDSS.xlsx` is the sole editable source for outfit data. `model/train_export.py` generates the model artifacts and `data/mon_do.csv`; never hand-edit generated outputs.
- FastAPI owns model inference, weather/Gemini integrations, authentication, and SQLite persistence. Flask is an HTTP client and must not import/load the model or call external services directly.
- Keep secrets in local environment variables or ignored `.env`; never print, commit, or copy API keys into tests, fixtures, docs, or logs.
- Preserve existing API validation, ownership checks, migrations, Vietnamese user-facing errors, and database rows. Use parameterized SQL and validate uploaded files before processing.

## Changes and verification

- Read the relevant implementation and tests before editing. Prefer a focused regression test for each bug.
- Keep changes narrow and maintain existing formatting and naming. Do not modify `data/DatasetDSS.xlsx` or commit `data/app.db`.
- From the project root, run `python -m pytest -q`; run `python tests/run_api_scenarios.py` for the measured API workflow.
- Start both local services with `python run_dev.py`; stop with Ctrl+C. API docs are at `/docs`.
- Generated artifacts: `model/outfit_model.joblib`, `model/model_metadata.json`, `model/charts/*.png`, and `data/mon_do.csv`.
- Every web route except `/login`, `/register`, `/healthz` and static files requires a logged-in session (enforced in `web/app.py` `require_login`); keep it that way.
- Do not commit virtual environments, Python bytecode, pytest caches, `.env`, or SQLite databases.

## Known scope

Persistent schedule management and image-based schedule parsing are not complete. Do not imply that these features work unless implementing and testing them in the current change.
