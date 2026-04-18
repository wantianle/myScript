# Repository Guidelines

## Project Structure & Module Organization

- `main.py` is the local entrypoint.
- `interface/` contains terminal-facing code:
  - `ui.py` for display only
  - `prompter.py` and `*_prompter.py` for input collection
  - `workflow.py` and `replay_workflow.py` for orchestration
- `core/` contains application logic:
  - `models.py` for domain models and raw schemas
  - `repository.py` for `meta.json` and cache persistence
  - `adapter/` for Docker/SSH execution
  - `engine/` for downloader, player, and recorder services
- `utils/` contains parsing helpers.
- `scripts/` contains shell entry scripts used by the Python layer.
- `tests/` contains minimal `unittest` unit tests.
- `config/` stores runtime YAML and tool config assets.
- `.venv/` is the project virtual environment and should be used for local Python commands when present.

## Build, Test, and Development Commands

- `bash scripts/setup.sh`
  Initializes the local environment and launches the tool.
- `python3 main.py`
  Runs the CLI directly when dependencies are already available.
- `.venv/bin/python main.py`
  Preferred local entrypoint when the project virtual environment already exists.
- `python3 -m unittest discover -s tests -p 'test_*.py'`
  Runs the current minimal unit test suite.
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
  Preferred test command when `.venv` is available.
- `python3 -m py_compile $(find . -path '*/.venv' -prune -o -name '*.py' -print)`
  Performs a repository-wide syntax check.

## Coding Style & Naming Conventions

- Python baseline is `3.8`. Do not use `list[str]`, `dict[str, int]`, or `X | Y`.
- Prefer dataclasses and typed models over loose `dict` payloads.
- Keep layering strict: `core/` must not print UI messages directly; `interface/` owns presentation.
- Use explicit names such as `task_entry`, `replay_record`, `channel_name`.
- Add short docstrings and return types to public functions.

## Testing Guidelines

- Use the built-in `unittest` framework.
- Only add minimal unit tests for basic functionality.
- Add focused tests for pure logic first: models, parsers, repositories, and planning helpers.
- Do not add UI or terminal interaction tests unless explicitly requested.
- Name files `tests/test_*.py` and keep each file scoped to one slice, for example `test_repository.py`.

## Commit & Pull Request Guidelines

- Commit format:
  - `[FIX][witt]...`
  - `[REFACTOR][witt]...`
  - `[TEST][witt]...`
  - `[DOCS][witt]...`
- Keep commits small and coherent. Commit after each meaningful step.
- Before opening a PR, run the relevant minimal unit tests and a syntax sweep.

## Architecture & Configuration Notes

- Read [ARCHITECTURE.md](/home/mini/dev/myScript/witt/ARCHITECTURE.md) before large refactors.
- Prefer `ctx.host`, `ctx.remote`, `ctx.docker`, `ctx.paths`, and `ctx.logic` over raw config dict access.
- Use repository classes for `meta.json` and library cache I/O instead of hand-writing JSON in service layers.



## Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.







