# Contributing to LabFlow Agent

## Development setup

```bash
pip install -e ".[dev]"
```

## Running checks

```bash
ruff check .
ruff format --check .
pytest tests/ -v -W ignore::DeprecationWarning
```

CI enforces all three as hard gates on every push and pull request: the `lint` job runs
`ruff check .` and `ruff format --check .`, the `test` job runs the 3.10/3.11/3.12 matrix,
and the `safety` job runs the raw-data-readonly / write-guard / boundary suites. Run them
locally before opening a PR.

## Adding a tool

1. Implement the function in `pico/tools/labflow.py` with signature `(ctx: ToolContext, args: dict) -> ToolResult`.
2. Define its JSON schema in `pico/tools/registry.py`.
3. Register it in `build_labflow_tool_registry`.
4. Add tests under `tests/`.

## Safety rules

- Raw data under `data/raw` or `data/batch_*` is read-only and enforced by `assert_raw_data_readonly`.
- Never expose arbitrary `run_shell`/`write_file`/`patch_file` in the LabFlow registry — those are generic-harness tools kept for safety tests only.
- New write paths must call `assert_raw_data_readonly` before writing.

## Integration tests

Set `PICO_RUN_INTEGRATION=1` and the relevant provider credentials to run `tests/integration/`.
Provider credentials are read from the environment; a repo-root `.env` file is
auto-loaded by `tests/integration/conftest.py`, so you can put `PICO_OPENAI_API_KEY`
etc. there instead of exporting them into your shell. `.env` is gitignored.
