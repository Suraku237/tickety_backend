# Tickety — Flask Backend Unit Tests

Object-oriented test suite (class-based `unittest.TestCase`, run by `pytest`).

## Layout
- `tests/base.py` — `BaseTestCase`: shared app/db/client setup + domain helpers.
- `tests/test_models.py` — `User` / `Queue` / `Ticket` model invariants.
- `tests/test_ticket_lifecycle.py` — status machine, carry-over, rolling-average ETA.
- `tests/test_routes.py` — auth + ticket endpoints via the Flask test client.

## Run
```bash
pip install -r requirements-test.txt
pytest            # from the project root (so `app`/`models` import correctly)
pytest --cov=.    # with coverage
```

## Adapt before running
Search the files for `ADAPT ME` / `ADAPT import`. Update:
1. The import block in `base.py` (`create_app`/`db` or `app`/`db`).
2. Model field names to match your real `models.py`.
3. Service imports (`compute_eta`, `estimated_wait`) and route URLs/JSON keys.
