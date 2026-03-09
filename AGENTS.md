# AGENTS

`AGENTS.md` is the single source of truth for AI agent behavior in this repository.

## Project Overview
- 4CAT is a Python based data analysis and collection tool that allows users to import, collect, and analyse datasets through a Web interface. Its key components are:
  - *Data sources*: Python scripts capable of importing or collecting external data, e.g. as API requests or file uploads.
  - *Processors*: modular Python scripts that process datasets for the purpose of data analysis. Processors can be chained to manipulate datasets outputted by other processors.
  - *Datasets*: Outputs of datasources and processors. Datasets can take shape as various files, most commonly as CSVs and NDJSONs but also as ZIPs, SVGs, PNGs, or HTMLs.
- 4CAT's three main design principles are:
  - *modularity*: 4CAT data sources and processors are meant to be compartmentalized to keep up with the volatile nature of social media APIs, data structures, and SOTA techniques in data analysis. This also ensures that one failing feature will not break 4CAT as a whole. 
  - *transparency*: It should be made clear *how* datasets are collected and processed. This is done through front-end GUI elements (e.g. detailed instructions in e.g. data source and processor instructions) as well as features like links to specific GitHub pages showing historical code versions. 
  - *traceability*: One should be able to retrace all collection and analyses steps in 4CAT. This works together with the other two principles.

## Architecture and Communication
- Repo with:
  - `backend/`: Python backend using Postgres. This:
    - Schedules workers via `WorkerManager` (`backend/lib/manager.py`), which polls the `JobQueue` and spawns workers as threads.
    - Parses and processes search requests.
    - Contains various helper methods and classes.
    - See `backend/database.sql` for the database definition.
    - `backend/workers/`: Built-in system workers (API handler, dataset cancellation, update checker, cleanup, metrics, extension management, etc.).
    - `backend/lib/`: Core backend classes—`worker.py` (BasicWorker), `processor.py` (BasicProcessor), `search.py` (Search), `manager.py` (WorkerManager), `preset.py`, `scraper.py`, `proxied_requests.py`.
  - `webtool/`: Python Flask, Jinja2, and JS front-end. This:
    - Defines the Web interface components and functionality.
    - Handles API requests to the backend.
    - Flask app is defined in `webtool/__init__.py`; WSGI entry point is `webtool/4cat.wsgi`.
    - Views are split by concern: `views/api_tool.py`, `views/api_standalone.py`, `views/views_dataset.py`, `views/views_admin.py`, `views/views_user.py`, `views/views_explorer.py`, `views/views_extensions.py`, `views/views_misc.py`, `views/views_restart.py`.
    - Jinja2 templates live in `webtool/templates/`; static assets in `webtool/static/`.
  - `common/`: Contains important files and classes used by both the back-end daemon and the front-end web app. Also contains shared helper functions and assets (i.e. static files) used for analyses. Key modules:
    - `common/lib/dataset.py` — `DataSet` class (extends `FourcatModule`).
    - `common/lib/fourcat_module.py` — `FourcatModule`, the root superclass for `DataSet` and `BasicProcessor`. Contains compatibility-checking logic.
    - `common/lib/module_loader.py` — `ModuleCollector`, which scans `processors/`, `datasources/`, `backend/workers/`, and extension dirs for workers/processors at startup.
    - `common/lib/database.py` — Postgres database wrapper.
    - `common/lib/helpers.py` — Shared utility functions.
    - `common/lib/user_input.py` — User input validation/sanitization.
    - `common/lib/config_definition.py` — Default config definitions.
    - `common/lib/llm.py` — LLM integration helpers.
    - `common/lib/job.py` / `common/lib/queue.py` — Job and JobQueue.
    - `common/config_manager.py` — `ConfigManager` (reads INI + database `settings` table + memcached caching) and `ConfigWrapper` (provides user-scoped config).
  - `datasources/`: Data sources are defined here. These can concern import definitions or full fledged scrapers. Each datasource folder follows a standard structure:
    - `__init__.py` — must define `DATASOURCE` (internal ID) and `NAME` (display name); optionally imports `init_datasource`.
    - A search worker file (e.g. `search_bsky.py`) whose `type` must follow the `{DATASOURCE}-search` or `{DATASOURCE}-import` naming convention.
    - Optional: `DESCRIPTION.md` (shown in the UI), `database.sql` (datasource-specific tables), Explorer CSS/HTML files.
  - `processors/`: Modular Python scripts that manipulate datasets in some way. This is very diverse; processors include machine learning analyses as well as 'Download images' and simple metric calculations. Organized into subdirectories by category: `audio/`, `conversion/`, `filtering/`, `machine-learning/`, `machine_learning/`, `metrics/`, `networks/`, `presets/`, `statistics/`, `text-analysis/`, `twitter/`, `visualisation/`.
  - `helper-scripts/`: Shared helper scripts. This importantly also contains various migration scripts to upgrade to new 4CAT versions. This often has to do with database manipulation. See the *Versioning and Migrations* section below.
  - `config/`: Configuration directory. Contains `config.ini` (INI-based runtime config), `module_config.bin` (pickled module-defined config options), `.current-version` (last-migrated version). `config/extensions/` holds installed extensions. Extensions are modular add-ons to 4CAT that are loaded in on startup. These can be data sources, processors, or workers. Folders here may be managed externally and concern symlinks. Each can have its own `requirements.txt`).

### Class Hierarchy
The core inheritance chain for data processing:
```
FourcatModule (common/lib/fourcat_module.py)
├── DataSet (common/lib/dataset.py)
└── BasicWorker (backend/lib/worker.py, threading.Thread)
    └── BasicProcessor (backend/lib/processor.py)
        └── Search (backend/lib/search.py)
```
- **BasicWorker**: Abstract thread-based worker. Key attributes: `type` (must match job ID), `max_workers` (parallelism limit, default 1). Workers with an `ensure_job` classmethod auto-queue recurring jobs on startup.
- **BasicProcessor**: Abstract processor. Required class attributes: `type`, `category`, `title`, `description`, `extension`. Required methods: `process()`, `get_options()`. The `options` class attribute is **deprecated**; use `get_options()` instead.
- **Search**: Abstract search worker for datasources. Its `type` should end with `-search` or `-import` (e.g. `bsky-search`).

### Database Schema (key tables in `backend/database.sql`)
- `settings` — key-value config store (name, value, tag).
- `jobs` — job queue (jobtype, remote_id, timestamps, interval for recurring).
- `datasets` — all datasets (key, type, key_parent for chaining, parameters as JSON, result_file, status, progress, etc.).
- `datasets_owners` — many-to-many user-dataset ownership.
- `annotations` — dataset item annotations.
- `metrics` — datasource metrics by date.
- `users` — user accounts (name, password hash, userdata JSON, tags JSONB).
- `access_tokens` — API access tokens.
- `users_favourites`, `users_notifications` — user preferences and notifications.

## Deployment

### Docker (primary)
- `docker-compose.yml` defines 4 services: `db` (Postgres), `memcached`, `backend`, `webtool`.
- All services are configured via a `.env` file (referenced by `env_file: .env`).
- The Docker image is based on `python:3.11-slim-trixie` (see `docker/Dockerfile`). Dependencies are installed via `pip install -r requirements.txt` (which just runs `pip install -e .` using `setup.py`). Gunicorn is installed separately for the frontend.
- **Backend entrypoint** (`docker/docker-entrypoint.sh`):
  1. Waits for Postgres and memcached to be healthy.
  2. Seeds the database from `backend/database.sql` if tables don't exist (fresh install).
  3. Removes stale PID lockfile.
  4. Runs `helper-scripts/migrate.py -y` to apply pending migrations.
  5. Runs `docker.docker_setup` to sync `.env` vars into `config/config.ini`.
  6. Starts the backend daemon via `python3 4cat-daemon.py start`.
- **Frontend entrypoint** (`docker/wait-for-backend.sh`): Waits for backend, runs frontend-specific migration, then starts Gunicorn (default: 4 workers, 4 threads, `gthread` class, binding `0.0.0.0:5000`).
- Named volumes: `4cat_db`, `4cat_data`, `4cat_config`, `4cat_logs`.

### Local development
- Backend: `python 4cat-daemon.py start` (or `restart` / `stop`).
- Python `>= 3.11` is required (enforced in `setup.py`).
- Install dependencies: `pip install -e .` (runs `setup.py` which unions core, processor, and extension packages).
- The `python-daemon` package is Unix-only and excluded on Windows (`os.name == "nt"`).

## Configuration
- **INI-based** (`config/config.ini`): Primary runtime config, read by `ConfigManager`. Docker's `docker_setup.py` syncs environment variables into this file.
- **Database**: The `settings` table stores runtime-configurable settings (name/value/tag). `ConfigManager` reads from both INI and database, with memcached caching.
- **Module config**: Module-defined `config` dicts (on worker classes) are collected by `ModuleCollector` at startup and cached to `config/module_config.bin`.
- **Legacy**: `config.py` in the repo root contains some legacy constants. Prefer `ConfigManager` / `config.ini` patterns.
- **Extensions**: Installed under `config/extensions/`. Each extension can include its own `requirements.txt` (auto-installed by `setup.py`). Enabled/disabled via `extensions.enabled` setting.

## Versioning and Migrations
- The current version is stored in the `VERSION` file (currently `1.53`). **Do not edit this file casually.**
- `config/.current-version` tracks the last-migrated version for the running instance.
- `helper-scripts/migrate.py` compares `VERSION` to `.current-version` and runs the appropriate `migrate-X.XX-X.XX.py` scripts from `helper-scripts/migrate/` in sequence.
- Migration scripts handle database schema changes, data transformations, and config updates between versions.
- Docker runs migration automatically on each startup.
- **For any schema or breaking change**: create a new `migrate-{old}-{new}.py` script and bump the `VERSION` file. Never edit existing migration scripts.

## Goals for Agents
- Preserve existing behavior unless a requested change intentionally modifies behavior.
- Prioritize correctness, testability, and clear error handling.
- Keep edits small, reviewable, and aligned with existing patterns and design principles.

## Coding Rules
- Follow existing project style, conventions, and naming.
- **Indentation**: The codebase uses **tabs** for Python indentation. Match this in all edits.
- Python `>= 3.11` is required. Use modern Python features (e.g. `match`, `|` for union types) when appropriate.
- Avoid adding dependencies unless clearly necessary. If a dependency is added, add it to the appropriate set in `setup.py` (`core_packages` or `processor_packages`) with a version pin.
- Add comments only when logic is non-obvious.
- Breaking changes are allowed when needed for correctness, maintainability, or delivery speed.
- Prefer minimal, targeted changes over broad refactors unless a broader change is the best path.

## Backend Guidelines
- Dependencies are managed via `setup.py` (not Poetry). Install with `pip install -e .`.
- Respect environment-based behavior documented in repository docs/config.
- For data-model or persistence changes:
  - Avoid destructive changes unless explicitly requested.
  - Call out migration or compatibility impact clearly.
  - If adding/altering database tables: update `backend/database.sql` for fresh installs and create a migration script in `helper-scripts/migrate/` for existing installs.
- When creating a new processor:
  - Subclass `BasicProcessor`. Define `type`, `category`, `title`, `description`, `extension`.
  - Implement `process()` and `get_options()`. Do **not** use the deprecated `options` class attribute.
  - Place it in the appropriate `processors/` subdirectory.
- When creating a new datasource:
  - Create a folder under `datasources/` with an `__init__.py` defining `DATASOURCE` and `NAME`.
  - Create a search worker extending `Search` with `type` set to `{DATASOURCE}-search` or `{DATASOURCE}-import`.
  - Optionally add `DESCRIPTION.md`, `database.sql`, and explorer files.

## Webtool Guidelines
- Use existing frontend formatting.
- Define reusable Jinja2 components when patterns emerge, but avoid over-engineering for future reuse.
- Views are organized by concern in `webtool/views/`. API endpoints are in `api_tool.py` and `api_standalone.py`.
- Static assets go in `webtool/static/`; templates in `webtool/templates/`.

## Testing Expectations
- Run tests with `pytest` from the repo root. Config is in `pytest.ini`.
- The test suite is in `tests/test_modules.py`. It validates:
  - **Logger initialization** (`test_logger`).
  - **Module loading** (`test_module_collector`): ensures all workers, processors, and datasources load without errors and no modules are missing.
  - **Processor validity** (`test_processors`, depends on `test_module_collector`): for every processor, checks it is a `BasicProcessor` subclass, has required attributes (`type`, `category`, `title`, `description`, `extension`), has required methods (`get_options`, `process`), that `get_options()` runs without error, that the deprecated `options` attribute is not present, and that the class can be instantiated.
  - **Datasource validity** (`test_datasources`, depends on `test_module_collector`): checks search worker naming conventions (`{DATASOURCE}-search` or `{DATASOURCE}-import`) and that each datasource `has_worker`.
- Tests mock `Database`, `ConfigManager`, `Job`, `JobQueue`, and `DataSet` extensively via `unittest.mock`. See fixtures in `test_modules.py` for patterns.
- **After making changes**: at minimum run `pytest` to ensure all modules still load and pass validation. New processors/datasources must pass `test_processors`/`test_datasources`.
- There are no integration or end-to-end tests. For complex logic, consider adding targeted unit tests.
- `ruff` is available as a dependency. Run `ruff check .` to lint changed files. No custom `ruff` config exists (defaults apply), but respect the tab-indentation convention.
- Make sure to check whether you are on a Unix-like system (macOS/Linux) or Windows to choose the correct commands.

## Safety and Guardrails
- Never commit secrets or real credentials.
- Avoid destructive operations by default (data deletion, schema resets, irreversible changes).
- Explicitly document risks, assumptions, and trade-offs when they matter.

## Change Communication
- For each meaningful change, report in a concise format covering:
  1. what changed
  2. why it changed
  3. how it was validated
  4. any suggested follow-up

## Preferred Workflow
1. Read relevant files first.
2. Propose a short plan for non-trivial changes.
3. Implement a minimal patch.
4. Run targeted validation (`pytest`, `ruff check`).
5. Report outcomes with file paths.

## Instruction Precedence
- If any other instruction file conflicts with `AGENTS.md`, follow `AGENTS.md`.