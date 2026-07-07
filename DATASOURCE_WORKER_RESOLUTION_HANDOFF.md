# Datasource ↔ worker resolution: context dump & handoff

**Parked:** 2026-07-07 · **Work branch:** `claude/practical-poincare-6d7b3d`
**Status:** exploration parked, NOT for merge as-is. Revisit after `output=Datasource` lands via `redesign`.

## Why this is parked

We set out to fix one bug (X/Twitter imports missing from the results filter) and ended up doing a
broad "centralize the `-search`/`-import` convention" sweep. On review, the sweep centralizes the
*lookup* but not the *convention itself*, and true centralization depends on structural facts that
the `output=Datasource` redesign is about to change. Rather than refactor against a moving target,
we're parking the full exploration here and will:

1. Wait for `output=Datasource` (the `outputs.py` archetypes) to merge via `redesign`.
2. Revisit with a forward-looking plan (see **Forward plan** below).
3. In the meantime, land only the **minimal fix for actually-broken things** (see **Minimal fix**).

---

## The original bug

X/Twitter datasets imported via Zeeschuimer did **not** appear in the data-source filter dropdown on
the results/overview page. (Also missing from the front-page "Zeeschuimer imports" group, and the
`/data-overview/twitter` page rendered a degraded panel.)

### Root cause

`ModuleCollector.expand_datasources()` derived each datasource's worker as `{datasource_id}-search`
only. The X/Twitter datasource has `DATASOURCE = "twitter"` but its worker's `type` is
**`twitter-import`**, so `workers.get("twitter-search")` returned `None` → `has_worker=False`,
`importable=False` → filtered out of the dropdown entirely.

---

## Key domain facts (the non-obvious stuff — read before touching this again)

1. **The `-search`/`-import` suffix is NOT semantic.** All 15 Zeeschuimer datasources
   (`is_from_zeeschuimer = True`) are import-only — every one raises `NotImplementedError` in
   `get_items`. **`twitter` is the *only* one named `-import`**; its 14 siblings (tiktok, instagram,
   threads, gab, facebook, pinterest, …) are equally import-only but named `-search`. What actually
   distinguishes import-vs-search behavior is `is_from_zeeschuimer` / per-worker `validate_query`,
   never the suffix.

2. **Renaming `twitter-import` → `twitter-search` is NOT an option.** Existing datasets store
   `type = "twitter-import"`. A rename would make every existing X/Twitter dataset render as
   "(Deprecated analysis)" (`item.type not in processors`, see `result-child.html`). This is why the
   fix must live in the loader, not the worker.

3. **The suffix fuses two separate facts into one string:**
   `twitter` + `-import` = *(which datasource)* + *(it is a collector/importer)*.

4. **A worker has NO `datasource` attribute — only `type`.** The explicit `datasource` value lives on
   **DataSets** (`dataset.parameters["datasource"]`, `dataset.py:1548`). So the *only* link from a
   worker back to its datasource id is the string prefix. **Some string lookup is therefore
   unavoidable** — there is no other bridge today. (`worker.prefix` exists on some workers but is a
   DB-table prefix, e.g. `4chan`, not the datasource identity.)

5. **`is_from_collector()` can't cleanly become `issubclass(cls, Search)`** because `search.py`
   imports `BasicProcessor` *from* `processor.py` — referencing `Search` in `processor.py` is a
   circular import. So it sniffs the suffix (`processor.py:1082`), exactly like `is_filter()` sniffs
   the category (which already has a `:todo: make this more robust`).

6. **The Zeeschuimer import itself already worked.** The import endpoint already tried
   `(f"{platform}-import", f"{platform}-search")`. The bug was purely in metadata/UI derivation, not
   in the import path.

---

## What is ACTUALLY broken vs cosmetic (drives the minimal fix)

**Actually broken (web-UI visible) for twitter:**
- Results-page datasource filter dropdown — twitter absent. *(the reported bug)*
- Front page — twitter miscategorized (shown as collectable, or absent from Zeeschuimer group).
- `/data-overview/twitter` — degraded: no "zeeschuimer" label, no references, empty example keys.

**Broken but API-only (no web-UI caller):**
- `GET /api/processor-options/twitter/` → `processor_type + "-search"` = `twitter-search` → 404. The
  web UI never calls processor-options with a datasource id (it uses `/api/datasource-form/`), so
  this only affected public-API callers.

**NOT broken for twitter (worked already, or harmless):**
- Zeeschuimer import endpoint — already handled both suffixes.
- `manager.validate_datasources` — already checked both suffixes.
- `datasource_metrics` — twitter isn't `is_local`, so it's skipped regardless.
- `manipulate_settings` label map — twitter defines no settings, so its label key is unused.
- `getboards` — twitter has no boards → returns False regardless.
- `check_search_queue` SQL (`LIKE '%-search'`) — only misses in-progress `-import` jobs in a count
  display; barely visible.
- `api_standalone` `endswith("-search")` — the adjacent `issubclass(Search)` already catches
  twitter-import.

---

## Minimal fix (do this after the revisit — ONLY the broken things)

Just three edits resolve every web-UI-visible bug:

1. Add `ModuleCollector.get_datasource_worker(datasource_id)` — try `{id}-search`, then `{id}-import`.
2. `expand_datasources()` uses it for `has_worker` / `has_options` / `importable`.
   *(fixes the filter dropdown + front-page categorization)*
3. `data_overview` (`views_misc.py`) uses it for `worker_class` and example-keys `dataset_type`.
   *(fixes the info page)*

Everything beyond these three is centralization/polish and should be deferred (see below).
Optionally also make `get_processor_options`'s datasource branch use the helper (one line) if you
care about the API-only case — but the web UI does not need it.

---

## The full sweep we did this session (PARKED on this branch — do not merge as-is)

For the record, so you know what's in the diff:

- `common/lib/module_loader.py`: `get_datasource_worker()` helper; `expand_datasources` uses it and
  now also stores `datasources[id]["worker_type"] = worker.type`.
- `webtool/views/views_misc.py`: `data_overview` + `getboards` use the helper / `worker.type`.
- `webtool/views/api_tool.py`:
  - dropped `get_processor_options`'s datasource-id overload (it's processor-only again),
  - added `GET /api/datasource-options/<id>/` (JSON options for a datasource — the counterpart to
    `/api/processor-options/`),
  - `datasource_form`, the import endpoint, queue-query, and `_get_search_class` all route through
    the helper,
  - `check_search_queue` SQL now matches `-import` too.
- `webtool/views/views_admin.py`: `manipulate_settings` reads `worker_type` from metadata instead of
  deriving `id + "-search"`.
- `backend/workers/datasource_metrics.py`: uses the resolved `worker.type` for the boards config key
  (dropped a dead `4chan→fourchan` translation).
- `backend/lib/manager.py`: `validate_datasources` uses the helper.
- `webtool/views/api_standalone.py`: uses the canonical `processor.is_from_collector()` (adds
  `-import`, keeps the `issubclass(Search)` net).

---

## The design tension (why the sweep isn't "done")

We centralized the **lookup** (`get_datasource_worker`) and cached its answer (`worker_type`). We did
NOT centralize the **definition of the convention** — the literal `("-search", "-import")` pair is
still hardcoded in ~6 places, each doing a *different* operation:

| Operation | Where |
|---|---|
| resolve worker (id → worker) | `module_loader.get_datasource_worker` |
| classify collector (worker) | `processor.is_from_collector` (`processor.py:1082`) |
| classify collector (dataset) | `dataset.py:2335` |
| strip type → id (display) | `template_filters.py:314` |
| match in SQL | `views_admin.py` + `api_tool.py` `LIKE` clauses |
| assert the convention | `tests/test_modules.py` |

If the convention ever changed, you'd edit ~6 spots. That's the real "not centralized."

---

## Forward plan (revisit after `output=Datasource` merges via `redesign`)

**What `output=Datasource` changes:** on the `output-shape` branch, `backend/lib/search.py` sets
`output = Datasource()` (from `common/lib/outputs.py`). That's an **explicit declaration that a worker
produces a datasource** — i.e. the "is this a collector?" fact, stated as data instead of inferred
from a suffix.

**So after it merges, the classification sites can improve:**
- `is_from_collector()` (and `dataset.py:2335`, `api_standalone.py`) could key off
  `isinstance(worker.output, Datasource)` instead of `type.endswith(...)`. This also sidesteps the
  circular-import block on the `issubclass(Search)` route.

**But `output` does NOT solve resolution.** `output=Datasource` says "*is* a datasource collector",
not "*belongs to* datasource X". So the id → worker mapping (`get_datasource_worker`) still needs the
exact-id lookup — and it must stay exact (`{id}-search`/`{id}-import`), because datasources share
prefixes (`tiktok` vs `tiktok-comments` vs `tiktok-urls`), so a prefix scan would be ambiguous.

**The real structural fix (independent of `output`):** give collector workers an explicit back-link
so the suffix is parsed exactly once. The `ModuleCollector` already pairs datasources ↔ workers at
load; it could set `worker.datasource = datasource_id` (and a collector flag) there. Then:
- worker → id = attribute read (no strip),
- is-collector = flag or `isinstance(output, Datasource)` (no suffix),
- id → worker = dict lookup,
- and the suffix convention lives in ONE place (the loader's wiring).

**Revisit agenda:**
1. Land the **minimal fix** (3 edits above) so the actual bug is gone regardless of redesign timing.
2. After `output=Datasource` merges: move the *classification* sites onto `isinstance(output, Datasource)`.
3. Decide whether to add the explicit `worker.datasource` back-link (kills the type→id strip and the
   remaining suffix duplication). Scope as its own small PR.
4. Consider a single `COLLECTOR_SUFFIXES = ("-search", "-import")` constant for whatever string sites
   genuinely remain (SQL can reference it via query building).

---

## Verification checklist (for whenever we land the real change)

**Automated (run first, in Docker — Python 3.9 host can't run the suite):**
- [ ] `pytest tests/test_modules.py` — module loading + naming-convention assertions. Main guard for
      the `module_loader` changes. (No integration/route tests exist; everything below is manual.)

**Manual — the bug & core UI:**
- [ ] Results-page datasource filter shows **X/Twitter**; filtering by it returns twitter datasets.
- [ ] Other datasources still appear + filter correctly.
- [ ] Front page: X/Twitter under **"Zeeschuimer imports"**, not the collectable list.
- [ ] `/data-overview/twitter` loads with the **zeeschuimer** label + references; `/data-overview/fourchan`
      still shows boards/metrics.

**Manual — create/import (highest-risk paths):**
- [ ] **Zeeschuimer import of X/Twitter end-to-end** creates a dataset.
- [ ] **Zeeschuimer import of a `-search` source** (TikTok/Instagram) still works (regression).
- [ ] Create-dataset form for a real search source (Bluesky/Tumblr): form loads, search queues.
- [ ] 4chan/8chan: boards populate in the create form.

**Manual — admin & metrics:**
- [ ] `/admin/settings` loads; setting groups show correct datasource **names** (twitterv2, bsky, fourchan).
- [ ] Backend startup log has **no** spurious "No search worker defined" errors.
- [ ] 4chan metrics still compute (data-overview graph populates).

**Manual — API surface (only if the API changes are kept):**
- [ ] `GET /api/datasource-options/twitter/` → options JSON.
- [ ] `GET /api/processor-options/twitter/` → 404; `GET /api/processor-options/<real_processor>/` works.
- [ ] `GET /api/check-search-queue/` returns counts (incl. `-import`).
- [ ] `/api/process/<processor>/` still excludes datasources.

---

## Related

- Memory: `project_datasource_worker_resolution.md`
- Redesign: `output-shape` branch — `common/lib/outputs.py` (`Datasource`, `Table`, `Filter`, …),
  `backend/lib/search.py` sets `output = Datasource()`.
