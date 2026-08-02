# Repository Guidelines

## Project Structure & Module Organization

MarketVault is a Python 3.11 package under `src/market_vault`. Core entry points are `cli.py`, `api.py`, and `service.py`. Data collection lives in `collectors/`, Parquet and DuckDB persistence in `storage/`, bar normalization in `normalization/`, and data-quality checks in `quality/`. Configuration examples live in `config/settings.yaml` and `config/universe.yaml`. Windows helper scripts are in `scripts/`. Tests are in `tests/` and mirror feature areas such as collectors, normalization, and quality.

Runtime output is expected under generated paths such as `data/`, `catalog/`, `manifests/`, and `reports/`; keep these out of source changes unless explicitly adding fixtures.

## Build, Test, and Development Commands

Create a local editable environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

Run the offline test suite with `pytest`. Initialize the DuckDB catalog with `market-vault --settings config/settings.yaml init-catalog`. Collect a closed trading date with `market-vault --settings config/settings.yaml collect --date 2026-07-31 --groups core_universe --interval 1m --session ALL --adjustment NONE`. Query curated bars with `market-vault --settings config/settings.yaml query --code US.MU --trade-date 2026-07-31 --interval 1m`.

## Coding Style & Naming Conventions

Use standard Python formatting: 4-space indentation, descriptive snake_case for functions and variables, PascalCase for classes, and type hints for public interfaces. Keep imports grouped as standard library, third-party, then local package imports. Prefer `pathlib.Path`, dataclasses, and small pure functions where the existing modules already do. CLI arguments should use kebab-case externally and snake_case internally.

## Testing Guidelines

Tests use `pytest` and are configured in `pyproject.toml` with `pythonpath = ["src"]` and `testpaths = ["tests"]`. Name files `test_*.py` and test functions `test_*`. Keep tests offline; they should not require moomoo OpenD, network access, or market-data permissions. Add focused fixtures or sample DataFrames near the tests that consume them.

## Commit & Pull Request Guidelines

This checkout does not include local Git history, so use concise imperative commit messages such as `Add parquet catalog migration` or `Fix option symbol parsing`. Pull requests should describe the data or CLI behavior changed, list tests run, mention any schema or storage-layout impact, and include sample command output when changing user-facing CLI behavior.

## Security & Configuration Tips

Do not commit account credentials, OpenD session details, or generated market-data archives. Keep local endpoint changes in `config/settings.yaml` minimal and document any required non-default OpenD host, port, quota, or permission assumptions in the PR.
