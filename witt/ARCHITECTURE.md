# Witt Architecture

## Scope

This document describes the current structure of `witt` after the recent refactors.
It is intended to keep future changes consistent and prevent the codebase from
drifting back into mixed-responsibility flow logic.

## Runtime Constraint

- Python baseline: `3.8`
- New code should avoid Python 3.9+ and 3.10+ only syntax.
  - Do not use `list[str]`, `dict[str, int]`, `X | Y`
  - Prefer `typing.List`, `typing.Dict`, `typing.Union`, `typing.Optional`

## Layering

### `interface/`

Responsible for terminal interaction and user-facing orchestration.

- `ui.py`
  - Pure presentation.
  - Prints banners, lists, status lines, playback info.
  - Should not contain business logic or persistence logic.

- `prompter.py`
  - Shared prompt primitives and generic terminal interactions.
  - Examples:
    - `get_user_input`
    - `get_int_input`
    - `get_confirm_input`
    - main menu selection

- `config_prompter.py`
  - Configuration-oriented prompts.
  - Responsible for collecting:
    - vehicle
    - date
    - split range
    - input/output paths
    - version file path

- `replay_prompter.py`
  - Replay-specific prompts.
  - Responsible for:
    - replay entry selection
    - SOC selection
    - replay range input
    - manual replay file input

- `channel_prompter.py`
  - Channel filtering prompts and channel aggregation presentation.

- `workflow.py`
  - Main search/slice/download orchestration.
  - Should stay thin.
  - Should coordinate use cases, not own prompt details.

- `replay_workflow.py`
  - Replay-related orchestration only.
  - Responsible for:
    - environment restore flow
    - standard replay flow
    - traffic-light replay flow

- `cli.py`
  - Application entry menu loop only.

### `core/`

Responsible for business logic, execution abstractions, and stateful services.

- `models.py`
  - Domain models and raw boundary schemas.
  - This is the preferred place for:
    - object construction helpers
    - cache/meta conversion helpers
    - schema normalization helpers

- `errors.py`
  - Core-layer exception types.
  - Core modules should raise structured exceptions instead of printing UI messages.

- `context.py`
  - Session-scoped state container.
  - Owns:
    - `AppConfig`
    - temp working area
    - library/work directory helpers
    - environment variable assembly

- `session.py`
  - Application composition root.
  - Wires context, services, and adapter selection.

- `runner.py`
  - Python-side script launcher.
  - Does not perform prompt logic.

- `adapter/`
  - Execution-channel adapters.
  - `docker.py` and `ssh.py` must remain transport concerns only.

- `engine/`
  - Business services.
  - `downloader.py`
    - batch planning
    - file slicing/sync
    - metadata output
  - `player.py`
    - library loading
    - playback plan construction
  - `recorder.py`
    - record info / split operations

### `utils/`

Pure helper logic.

- `parser.py`
  - parsing and normalization helpers
  - should avoid terminal orchestration concerns

## Model Boundaries

These model groups are now explicit and should remain the default path for new work.

### Task and Flow Data

- `TaskEntry`
  - parsed from manifest
  - used by workflow, downloader, channel selection

### Config Data

- `AppConfig`
- `HostConfig`
- `RemoteConfig`
- `DockerConfig`
- `PathsConfig`
- `LogicConfig`

Use `ctx.host`, `ctx.remote`, `ctx.docker`, `ctx.paths`, `ctx.logic`
instead of raw `config["..."]` access.

### Replay Data

- `ReplayRecord`
- `LibraryEntry`
- `RecordInfo`
- `ChannelInfo`

### Metadata Data

- `TagInfo`
- `RecordMeta`

`meta.json` read/write should use `RecordMeta` and `TagInfo` rather than hand-built dicts.

## Raw Boundary Schemas

`models.py` contains `TypedDict` definitions for raw config/cache/meta boundaries.

Use them at the edges:

- YAML/config loading
- JSON cache loading
- metadata loading

Use dataclasses inside the application.

## Error-Handling Rules

- `core/` should not call `ui.print_status(...)`
- `core/` raises typed exceptions from `core/errors.py`
- `interface/` decides how to present those failures
- Avoid `except Exception as e: raise e`
- Prefer:
  - let the exception propagate
  - or `raise SomeError(...) from e`

## Naming Rules

- Prefer nouns for data objects:
  - `TaskEntry`, `ReplayRecord`, `RecordMeta`
- Prefer verb phrases for actions:
  - `load_library`, `build_playback_plan`, `plan_download`
- Prefer explicit names over short temporary names:
  - `task_entry` instead of `t`
  - `replay_record` instead of `r`
  - `channel_name` instead of `name` when scope is ambiguous

## Function Contract Rules

- Public functions should have:
  - explicit return types
  - short docstrings when behavior is not trivial
- Helper functions should return typed objects where possible
- Avoid passing wide `dict` payloads across module boundaries when a model already exists

## Testing Strategy

Current tests are intentionally minimal and focused on stable pure logic.

Prefer testing first in these layers:

1. `core/models.py`
2. `utils/parser.py`
3. small orchestration helpers with no external process dependency

Do not start with docker/ssh/process-heavy integration tests unless needed.

## Refactor Priorities Going Forward

1. Continue reducing broad exception handling in interface helpers.
2. Tighten remaining wide type hints (`list`, `dict`, broad `Exception` paths).
3. Reduce service-layer data assembly where models can own it.
4. Add more focused regression tests for:
   - downloader planning
   - replay selection behavior
   - metadata merge/update logic
5. Only after boundaries are stable, consider migrating more shell logic into Python.
