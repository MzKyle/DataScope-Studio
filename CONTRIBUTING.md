# Contributing

Thanks for helping improve DataScope Studio. This repository is organized as a local-first
monorepo, so changes should keep the desktop UI, API, CLI, and core package contracts aligned.

## Development Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

cd apps/desktop
npm install
```

## Branches and Commits

- Create focused branches from `main`.
- Keep unrelated formatting, generated files, and local datasets out of commits.
- Use clear commit messages that describe the behavior change.

## Code Guidelines

- Keep public Python imports stable: `datascope_core`, `datascope_cli`, and `datascope_api`.
- Prefer adapter/template additions over special cases in the workspace layer.
- Keep the desktop UI responsive; large datasets should be processed in the backend.
- Add or update tests for adapters, mapping, query templates, API flows, and CLI commands.

## Checks Before a PR

```bash
pytest -q
cd apps/desktop && npm run build
cd apps/desktop/src-tauri && cargo check
git diff --check
```

## Documentation

When adding a feature, update the docsify site under `docs/` if the feature changes user
workflow, public API behavior, CLI commands, or project structure.
