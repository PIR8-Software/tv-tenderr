# Contributing to tv-tenderr

Thanks for helping improve tv-tenderr.

## Development setup

1. Clone the repo.
2. Create and activate a virtual environment.
3. Install the project dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

4. Install pre-commit hooks:

```bash
pre-commit install
```

## Running checks locally

```bash
pytest -q
ruff check .
black --check .
isort --check-only .
```

## Pull request expectations

- Keep changes focused and easy to review.
- Add or update tests when behavior changes.
- Ensure CI passes before requesting review.
- Keep secrets and credentials out of the repository.

## Reporting issues

Use the GitHub issue templates and include steps to reproduce the bug, expected behavior, and the environment you used.
