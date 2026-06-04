"""
CI glue for the Zeeschuimer `map_item` sync workflow: translation-matrix
planning (`plan-matrix`) and PR-body construction (`build-pr-body`).

This logic used to live as Python heredocs embedded in
`.github/workflows/zeeschuimer_map_item_sync.yml`. It was moved here so it can
be unit-tested and linted like the rest of the codebase.

IMPORTANT: this module is intentionally pure-stdlib and MUST NOT import
`map_item_converter` (or anything under `common/`). The `detect` job runs
`plan-matrix` WITHOUT installing the LLM dependencies (langchain etc.), so any
heavy import here would break it.

Usage (from the 4CAT repo root):
    python helper-scripts/map_item_ci.py plan-matrix
    python helper-scripts/map_item_ci.py build-pr-body --manifest manifest.json --out pr_body.md

`plan-matrix` reads EVENT_NAME / INPUTS_FILES / INPUTS_BOOTSTRAP / BEFORE_SHA /
AFTER_SHA from the environment and writes `mode` and `matrix` to $GITHUB_OUTPUT.
`build-pr-body` reads MODULE / BOOTSTRAP / BEFORE_SHA / AFTER_SHA / RUN_ID /
EVENT_NAME / REPO, writes the PR body to `--out`, and writes `title` to
$GITHUB_OUTPUT.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Callable, Optional


# Strict shape for a datasource path: `datasources/<module>/search_<name>.py`.
# Anchored and restricted to a safe charset (no shell metacharacters) so that a
# path coming from `git diff` or, especially, a `workflow_dispatch` `files`
# input can be interpolated into the sync job's `--files` shell argument
# without any risk of command injection. Anything not matching is dropped and
# logged (never silently passed through).
DATASOURCE_PATH_RE = re.compile(r"^datasources/[A-Za-z0-9_-]+/search_[A-Za-z0-9_]+\.py$")

# Pathspec used to limit the push-event diff to datasource search files.
_DATASOURCE_PATHSPEC = "datasources/*/search_*.py"


def _git_diff_names(before: str, after: str) -> list[str]:
    """
    Names of datasource search files changed between two commits. Returns an
    empty list (rather than raising) if git can't resolve the range — e.g. a
    shallow clone that doesn't contain `before`. The caller treats "can't tell"
    the same as "nothing changed".
    """
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", before, after, "--", _DATASOURCE_PATHSPEC],
            text=True,
        )
    except subprocess.CalledProcessError:
        return []
    return [line for line in out.splitlines() if line.strip()]


def plan_matrix(
    event_name: str,
    inputs_files: str,
    inputs_bootstrap: bool,
    before: str,
    after: str,
    git_diff: Optional[Callable[[str, str], list[str]]] = None,
) -> tuple[str, list[dict], list[str]]:
    """
    Decide what to translate. Returns `(mode, matrix, rejected)`:

    - mode: "bootstrap" | "files" | "none"
    - matrix: list of `{"module", "files", "bootstrap"}` entries for the
      `sync` job's matrix.
    - rejected: candidate paths dropped because they don't match
      `DATASOURCE_PATH_RE` (logged by the caller for transparency).

    `git_diff` is injectable for testing; it defaults to a real `git diff`.
    """
    inputs_files = (inputs_files or "").strip()

    # Bootstrap is special: a single PR covering every datasource. An explicit
    # `files` input overrides bootstrap; honor that.
    if event_name == "workflow_dispatch" and inputs_bootstrap and not inputs_files:
        return "bootstrap", [{"module": "bootstrap", "files": "", "bootstrap": True}], []

    # Resolve the candidate file list.
    if event_name == "workflow_dispatch" and inputs_files:
        candidates = inputs_files.split()
    else:
        if git_diff is None:
            git_diff = _git_diff_names
        candidates = git_diff(before, after)

    # Validate before anything reaches a shell. Drop (and report) anything that
    # isn't a plain `datasources/<module>/search_<name>.py` path.
    files: list[str] = []
    rejected: list[str] = []
    for path in candidates:
        path = path.strip()
        if not path:
            continue
        if DATASOURCE_PATH_RE.match(path):
            files.append(path)
        else:
            rejected.append(path)

    # Group by module: datasources/<module>/search_*.py
    modules: dict[str, list[str]] = {}
    for path in files:
        parts = path.split("/")
        modules.setdefault(parts[1], []).append(path)

    if not modules:
        return "none", [], rejected

    matrix = [
        {"module": mod, "files": " ".join(sorted(paths)), "bootstrap": False}
        for mod, paths in sorted(modules.items())
    ]
    return "files", matrix, rejected


def _git_python_diff(before: str, after: str, python_file: str) -> str:
    """`git diff before..after -- <python_file>`; "" if the range can't resolve."""
    try:
        return subprocess.check_output(
            ["git", "diff", "{}..{}".format(before, after), "--", python_file],
            text=True,
        )
    except subprocess.CalledProcessError:
        return ""


def build_pr_body(
    manifest: dict,
    module: str,
    is_bootstrap: bool,
    before: str,
    after: str,
    run_id: str,
    event_name: str,
    repo: str,
    python_diff: Optional[Callable[[str, str, str], str]] = None,
) -> tuple[str, str]:
    """
    Build the draft-PR `(title, body)` from a translation manifest. `python_diff`
    is injectable for testing; it defaults to a real `git diff` and is only
    invoked for `push` events.
    """
    if python_diff is None:
        python_diff = _git_python_diff

    model = manifest.get("model", "(unknown)")
    provider = manifest.get("provider", "ollama")
    structured_output = manifest.get("structured_output", False)
    stream = manifest.get("stream", False)
    total_duration = manifest.get("total_duration_seconds")
    entries = manifest.get("entries", [])

    short_sha = after[:7]
    lines: list[str] = []
    lines.append(
        "> :robot: This PR was auto-generated by the [4CAT map_item sync "
        "workflow](https://github.com/{}/actions/runs/{}). The JavaScript was "
        "produced by an LLM and **requires human review** before merging — "
        "including manual fixes for any lint warnings flagged below.".format(repo, run_id)
    )
    lines.append("")
    lines.append("## Generation parameters")
    lines.append(
        "- **Model:** `{}` (provider: `{}`, structured output: `{}`, stream: `{}`)".format(
            model, provider, structured_output, stream
        )
    )
    if total_duration is not None:
        lines.append("- **Total LLM time:** {}s".format(total_duration))
    if is_bootstrap:
        lines.append(
            "- **Trigger:** manual `workflow_dispatch` with `bootstrap=true` "
            "(initial sync of all Zeeschuimer datasources)."
        )
    elif event_name == "workflow_dispatch":
        lines.append("- **Trigger:** manual `workflow_dispatch` for `{}`.".format(module))
    else:
        lines.append(
            "- **Trigger:** push of [`{}`](https://github.com/{}/commit/{}) to 4CAT "
            "master (module: `{}`).".format(short_sha, repo, after, module)
        )
    lines.append("")

    ok = [e for e in entries if e["status"] == "ok"]
    ok_with_warnings = [e for e in ok if e.get("lint_warnings")]
    failed = [e for e in entries if e["status"] == "failed"]
    skipped = [e for e in entries if e["status"] == "skipped"]

    lines.append("## Summary")
    lines.append("- :white_check_mark: {} translated".format(len(ok)))
    if ok_with_warnings:
        lines.append(
            "- :warning: {} translated with lint warnings (require manual fix)".format(
                len(ok_with_warnings)
            )
        )
    lines.append("- :x: {} failed".format(len(failed)))
    lines.append("- :grey_question: {} skipped".format(len(skipped)))
    lines.append("")

    if ok:
        lines.append("| Datasource | Module | Time | Warnings |")
        lines.append("|---|---|---:|---:|")
        for entry in ok:
            dur = entry.get("duration_seconds")
            dur_cell = "{}s".format(dur) if dur is not None else "—"
            warn_count = len(entry.get("lint_warnings") or [])
            warn_cell = ":warning: {}".format(warn_count) if warn_count else "—"
            lines.append(
                "| `{}` | `{}` | {} | {} |".format(
                    entry["python_file"], entry["js_file"], dur_cell, warn_cell
                )
            )
        lines.append("")

    if ok_with_warnings:
        lines.append("## :warning: Lint warnings — fix before merging")
        lines.append("")
        lines.append(
            "The following datasources translated successfully but the static lint "
            "flagged issues that need human fixes. The auto-generated code was "
            "spliced into the JS module as-is; please patch the file directly in "
            "this PR."
        )
        lines.append("")
        for entry in ok_with_warnings:
            lines.append("**`{}` -> `{}`**".format(entry["python_file"], entry["js_file"]))
            for w in entry["lint_warnings"]:
                lines.append("- {}".format(w))
            lines.append("")

    for entry in ok:
        dur = entry.get("duration_seconds")
        header_dur = " ({}s)".format(dur) if dur is not None else ""
        warn_marker = " :warning:" if entry.get("lint_warnings") else ""
        lines.append(
            "## `{}` -> `{}`{}{}".format(
                entry["python_file"], entry["js_file"], header_dur, warn_marker
            )
        )
        if entry.get("commentary"):
            lines.append("**LLM commentary:**")
            lines.append("")
            lines.append("> " + entry["commentary"].replace("\n", "\n> "))
            lines.append("")
        if event_name == "push":
            diff = python_diff(before, after, entry["python_file"])
        else:
            diff = ""
        if diff.strip():
            lines.append("<details><summary>Python diff</summary>")
            lines.append("")
            lines.append("```diff")
            lines.append(diff.rstrip())
            lines.append("```")
            lines.append("</details>")
            lines.append("")

    if failed:
        lines.append("## Failures")
        for entry in failed:
            dur = entry.get("duration_seconds")
            dur_str = " (after {}s)".format(dur) if dur is not None else ""
            lines.append(
                "- `{}`{}: {}".format(
                    entry["python_file"], dur_str, entry.get("error", "(no error message)")
                )
            )
        lines.append("")

    if skipped:
        lines.append("## Skipped")
        for entry in skipped:
            lines.append("- `{}`: {}".format(entry["python_file"], entry.get("error", "")))
        lines.append("")

    body = "\n".join(lines)

    # Title is single-module in the matrix path; bootstrap is its own
    # special-case (one PR covering every datasource).
    ok_modules: list[str] = []
    for entry in ok:
        parts = entry["python_file"].split("/")
        if len(parts) >= 2 and parts[0] == "datasources":
            mod = parts[1]
            if mod not in ok_modules:
                ok_modules.append(mod)

    if is_bootstrap:
        title = "Auto-translated map_item updates from 4CAT (bootstrap, {} datasources)".format(
            len(ok_modules)
        )
    elif not ok_modules:
        title = "Auto-translated map_item updates from 4CAT: {}".format(module)
    else:
        title = "Auto-translated map_item updates from 4CAT: {}".format(", ".join(ok_modules))

    return title, body


def set_output(name: str, value: str) -> None:
    """
    Append a `name=value` step output to $GITHUB_OUTPUT using the heredoc
    delimiter form, which is safe for values containing `\\n` or `=` (a plain
    `name=value` line can be abused to inject extra outputs). No-op when
    $GITHUB_OUTPUT is unset (e.g. running locally).
    """
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        return
    # A delimiter that cannot appear in our values. If it somehow does, strip it
    # rather than emit a malformed/forgeable block.
    delim = "ghadelim_{}_b3f9c1".format(name)
    safe_value = value.replace(delim, "")
    with open(out_path, "a", encoding="utf-8") as f:
        f.write("{name}<<{delim}\n{value}\n{delim}\n".format(name=name, delim=delim, value=safe_value))


def _cmd_plan_matrix() -> int:
    mode, matrix, rejected = plan_matrix(
        event_name=os.environ.get("EVENT_NAME", ""),
        inputs_files=os.environ.get("INPUTS_FILES", ""),
        inputs_bootstrap=os.environ.get("INPUTS_BOOTSTRAP", "").lower() == "true",
        before=os.environ.get("BEFORE_SHA", ""),
        after=os.environ.get("AFTER_SHA", ""),
    )

    if rejected:
        print(
            "Plan: dropped {} path(s) not matching `datasources/<module>/search_<name>.py`:".format(
                len(rejected)
            )
        )
        for path in rejected:
            print("  - {!r}".format(path))

    set_output("mode", mode)
    set_output("matrix", json.dumps(matrix))

    if mode == "bootstrap":
        print("Plan: bootstrap (single PR)")
    elif mode == "none":
        print("Plan: nothing to translate")
    else:
        print("Plan: {} module(s)".format(len(matrix)))
        for entry in matrix:
            print("  - {}: {}".format(entry["module"], entry["files"]))
    return 0


def _cmd_build_pr_body(manifest_path: str, out_path: str) -> int:
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    title, body = build_pr_body(
        manifest,
        module=os.environ["MODULE"],
        is_bootstrap=os.environ.get("BOOTSTRAP", "").lower() == "true",
        before=os.environ.get("BEFORE_SHA", ""),
        after=os.environ.get("AFTER_SHA", ""),
        run_id=os.environ.get("RUN_ID", ""),
        event_name=os.environ.get("EVENT_NAME", ""),
        repo=os.environ.get("REPO", ""),
    )

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(body)
    print("Wrote {} ({} chars)".format(out_path, len(body)))

    set_output("title", title)
    print("PR title: {}".format(title))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("plan-matrix", help="Emit the translation matrix to $GITHUB_OUTPUT.")

    body = sub.add_parser("build-pr-body", help="Build the draft-PR body from a manifest.")
    body.add_argument("--manifest", required=True, help="Path to the translation manifest JSON.")
    body.add_argument("--out", required=True, help="Where to write the PR body markdown.")

    args = parser.parse_args(argv)

    if args.command == "plan-matrix":
        return _cmd_plan_matrix()
    if args.command == "build-pr-body":
        return _cmd_build_pr_body(args.manifest, args.out)
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
