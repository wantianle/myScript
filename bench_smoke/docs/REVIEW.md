<!-- 历史文档 — 当前行为以 README + docs/V1_SUMMARY.md 为准 -->
## CRITICAL
- [cli.py:124] `run_many(datasets, packages, config)` is called once and its result is discarded, then called again at line 128; for multi-dataset runs this will execute installs/copies/module switching/playback/recording twice → remove the first call and keep only `summaries = run_many(...)`.
- [recorder.py:42] `_build_record_command()` calls `config.record_command_template.format(output=output_path)`, but the default template and config validation require `{output_dir}`; `start_recorder` will fail with `KeyError: 'output_dir'` before recording can start → change the format argument to `output_dir=output_dir` or change the template/validator consistently.
- [step_runner.py:110] mutated `RunContext` fields are never persisted after step execution; `prepare_data`, `start_recorder`, and `stop_recorder` update `local_dataset_path`, `record_output_dir`, and `generated_mcaps` in memory only, so debug mode with `--run-id` will not have prerequisites available → call `result_store.save_context(context)` after every step result is persisted, especially after successful mutating steps.
- [playback.py:60] wildcard playback is likely not implemented as intended: the command is executed as an argv list through `subprocess.run`, so shell wildcard expansion does not happen despite the file comment saying it does; if `mkit play -f` does not expand globs internally, playback receives a literal `*` path → either explicitly expand with `glob.glob()` and pass concrete files, or intentionally execute through a controlled shell wrapper if `mkit` requires shell-style wildcard input.

## WARNING
- [versioning.py:22] remote calls never pass `config.ssh_password` to `run_remote`, and the same omission appears in module control, recorder, and metadata; `BENCH_SMOKE_SSH_PASSWORD` is loaded but effectively ignored, so password-only benches will fail SSH → either pass `password=config.ssh_password` in every `run_remote` call or wrap remote execution behind a config-aware helper.
- [command_runner.py:117] if password support is wired later, `sshpass -p <password>` is stored in `CommandResult.command` and persisted into step JSON files, leaking credentials → use `sshpass -e` with an environment variable and scrub/mask password-bearing argv before storing command results.
- [data_prep.py:42] NAS validation only checks `test -d /media/nas`, which passes for an unmounted empty directory and does not satisfy the SPEC requirement to verify the mount before rsync → check `mountpoint -q /media/nas` or parse `/proc/mounts`, then fail before source validation/rsync.
- [data_prep.py:69] destination directories are created with `mkdir -p` and no pre-existence guard, violating the MVP default of not reusing historical localized data directories → fail if `dest_path` already exists or is non-empty unless an explicit future `--reuse` option is provided.
- [orchestrator.py:270] `_load_existing_context()` silently creates a fresh context when the requested `run_id` cannot be loaded, then overwrites `ctx.run_id` without changing `run_dir`; debug runs can write under a different directory than the requested run and lose prerequisite state → fail clearly when `--run-id` is not found or cannot be loaded.
- [logging_setup.py:68] CLI initializes logging to `config.run_root/run.log`, but no code reinitializes logging to each created `run_dir`; this breaks the DESIGN expectation that each run has its own `run.log` under the run directory → call `setup_logging(context.run_dir)` immediately after `create_run_context()`.
- [manifest.py:58] `DatasetEntry(**e)` will raise a raw `TypeError` if the manifest has extra keys, despite the contract requiring manifest-format failures to become `ManifestError` → filter known fields or catch `TypeError` and rethrow `ManifestError` with entry context.
- [versioning.py:61] user-provided package versions are interpolated directly into remote shell strings; similar direct interpolation exists for remote paths and module names → validate allowed characters and/or use `shlex.quote()` for every shell-fragment value before building SSH commands.
- [recorder.py:225] `_discover_mcaps()` uses unquoted `record_output_dir` in a remote `find` command; dataset IDs from manifests can contain shell-sensitive characters and break the command or worse → quote with `shlex.quote(record_output_dir)` before interpolation.
- [metadata.py:52] `mkit info '{}'`.format(mcap_path) is not safe for paths containing single quotes and can produce invalid shell syntax → use `shlex.quote(mcap_path)`.

## SUGGESTION
- [config.py:155] `_dict_to_config()` creates an unused `defaults = ToolConfig()` variable → remove it.
- [orchestrator.py:103] `recorder_started` is set before `start_recorder` actually succeeds; current fail-fast behavior masks most impact, but the state name is misleading → set it only after the `start_recorder` step returns `SUCCESS`.
- [step_runner.py:117] `log_path` is assigned after `save_step_result()` writes the JSON, so the persisted step file does not include its own `log_path` field → set `result.log_path` before writing, or rewrite after assignment.
- [command_runner.py:49] `_run_argv()` computes `started_at` but never uses it → remove the dead local variable.
- [recorder.py:220] using `find` on soc2 means generated `.mcap` paths are remote paths; if later local metadata/upload expects local visibility, this boundary should be documented in artifacts → add an explicit artifact field like `"mcap_host": "soc2"`.
- [module_control.py:29] module stop/start is not idempotent; if `supervisorctl stop` returns non-zero for already-stopped modules, debug reruns may fail unnecessarily → after bench behavior is confirmed, normalize already-stopped/already-running states if appropriate.

## PHASE 5 VALIDATION REPORT

### Real bench validation target
- issue: `7037566695`
- title: `mdrive4_鬼探头二轮车_自车刹车不及时`
- source input: `/media/nas/mdrive4/20260703/XZT500018/bag/record_20260703_142922/record.00050.144153.mcap`
- validation run directory: `/mdrive_data/bench_smoke_runs/20260706/7037566695_152522_99e3f082`

### What was validated on real bench
- `inspect_version` succeeded on bench
- `prepare_data` succeeded with a single-file `.mcap` input
- `switch_modules` succeeded after bench-specific debug module naming was corrected in Phase 5 config (`Debug_Driver-LiDAR`)
- `start_recorder` succeeded using supervisor-managed `Recorder`
- `playback` succeeded on soc2 against the localized dataset copy
- `stop_recorder` succeeded and discovered real output files by time-window scan under `/mdrive_data/bag`
- `collect_metadata` succeeded and collected `mkit info` for both generated `.mcap` files
- `summarize` debug step succeeded

### Generated output discovered on bench
- `/mdrive_data/bag/record_20260706_164028/record.00000.164029.mcap`
- `/mdrive_data/bag/record_20260706_164028/record.00001.164044.mcap`

### Bench-specific fixes proven necessary during Phase 5
- `command_runner.py`: localhost/self-target soc2 commands must execute locally instead of self-SSH
- `command_runner.py`: localhost `sudo` commands need non-interactive `sudo -S` password injection
- `data_prep.py`: source dataset can be a single `.mcap` file, not only a directory
- `data_prep.py`: soc2 may not have `rsync`; Python stdlib copy fallback is required
- `module_control.py`: on supervisor connection failures, capture `journalctl -xeu mdrive.service -n 50 --no-pager` diagnostics
- `recorder.py`: supervisor-managed `Recorder` is more reliable on this bench than shell-launched `mkit record`
- `playback.py`: local playback must use bench-stable setup behavior plus the confirmed absolute `mkit` binary path
- `metadata.py`: local `mkit info` must use the same stable setup/runtime approach as playback
- `step_runner.py`: `dataclasses.asdict()` encoding path needed a type-safe dataclass-instance guard for static analysis

### Important note about persisted summary status
The reused Phase 5 run id contains earlier failed debug attempts during bring-up, so the persisted `summary.json` still reports historical failure state (`failed_step=switch_modules`) even though the final debug-step chain reached successful execution through `collect_metadata` and `summarize`. For a clean all-green summary artifact, rerun the final validated workflow on a fresh run id.
