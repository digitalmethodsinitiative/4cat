"""
Tests for the Zeeschuimer map_item sync helper scripts:

- `helper-scripts/map_item/converter.py` — path derivation, JS-marker splicing,
  the static lint, and the comment stripper.
- `helper-scripts/map_item/ci.py` — translation-matrix planning and PR-body
  construction (the CI glue).

These import the helper scripts directly (they have no heavy dependencies once
`LLMAdapter` is imported lazily), so they run on host Python as well as in the
`4cat_backend` container via `docker exec 4cat_backend pytest`.
"""
import sys
from pathlib import Path

import pytest

# helper-scripts is not a package; put it on sys.path so the modules (and their
# sibling `from rules import ...`) import cleanly.
HELPER_DIR = Path(__file__).resolve().parent.parent / "helper-scripts/map_item"
if str(HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(HELPER_DIR))

import ci  # noqa: E402
import converter as mic  # noqa: E402
import rules  # noqa: E402


# --------------------------------------------------------------------------- #
# python_to_js_module — convention-based path derivation
# --------------------------------------------------------------------------- #

def test_python_to_js_module_conventions():
    f = mic.python_to_js_module
    assert f("datasources/tiktok/search_tiktok.py") == "modules/tiktok.js"
    # filename, not directory, drives the mapping (documented edge cases):
    assert f("datasources/xiaohongshu/search_rednote.py") == "modules/rednote.js"
    assert f("datasources/twitter-import/search_twitter.py") == "modules/twitter.js"
    # underscores in the base become hyphens
    assert f("datasources/x/search_a_b.py") == "modules/a-b.js"


def test_python_to_js_module_rejects_non_conforming():
    f = mic.python_to_js_module
    assert f("datasources/x/notsearch.py") is None
    assert f("datasources/x.py") is None
    assert f("notdatasources/x/search_x.py") is None
    assert f("datasources/x/search_.py") is None  # empty base


# --------------------------------------------------------------------------- #
# splice_into_module — the C1 regression surface
# --------------------------------------------------------------------------- #

def _translation(fn, helpers=None, imports=None):
    return {
        "map_item_function": fn,
        "helpers_to_add": helpers or [],
        "imports_to_add": imports or [],
        "commentary": "",
    }


def test_splice_appends_when_no_markers():
    out = mic.splice_into_module(
        "const a = 1;\n",
        _translation("export function map_item(item){ return new MappedItem({}); }"),
        "datasources/x/search_x.py",
    )
    assert "const a = 1;" in out
    assert mic.BLOCK_MARKER_START in out and mic.BLOCK_MARKER_END in out
    assert "map_item" in out


def test_splice_replace_preserves_regex_escapes():
    """C1: a regex literal containing `\\w` must NOT raise `re.error` on the
    re-sync (replace) path, and must survive verbatim."""
    start, end = mic.BLOCK_MARKER_START, mic.BLOCK_MARKER_END
    existing = f"const a = 1;\n{start}\n// old\nexport function map_item(){{}}\n{end}\nconst b = 2;\n"
    out = mic.splice_into_module(
        existing,
        _translation(r"export function map_item(item){ return item.text.match(/#(\w+)/g) ?? []; }"),
        "datasources/x/search_x.py",
    )
    assert r"/#(\w+)/g" in out                 # escape preserved verbatim
    assert "const a = 1;" in out and "const b = 2;" in out  # surrounding code intact
    assert "// old" not in out                 # old block replaced, not duplicated
    assert out.count(start) == 1


def test_splice_replace_preserves_newline_escape():
    """C1: `"\\n"` must stay a two-char escape, not be turned into a raw newline
    inside the string literal (which would be a JS syntax error)."""
    start, end = mic.BLOCK_MARKER_START, mic.BLOCK_MARKER_END
    existing = f"{start}\nold\n{end}\n"
    out = mic.splice_into_module(
        existing,
        _translation(r'export function map_item(item){ return item.tags.join("\n"); }'),
        "datasources/x/search_x.py",
    )
    assert r'join("\n")' in out          # backslash-n preserved
    assert 'join("\n")' not in out       # NOT a raw newline (this literal has a real \n)


def test_splice_idempotent_append_then_replace():
    """Full re-sync lifecycle: first splice appends, second replaces. Both must
    succeed (no re.error) and the block must not be duplicated."""
    t = _translation(r"export function map_item(i){ return i.t.match(/#(\w+)/g); }")
    once = mic.splice_into_module("base\n", t, "datasources/x/search_x.py")
    twice = mic.splice_into_module(once, t, "datasources/x/search_x.py")
    assert twice.count(mic.BLOCK_MARKER_START) == 1
    assert twice.count(mic.BLOCK_MARKER_END) == 1
    assert r"/#(\w+)/g" in twice


def test_splice_includes_helpers():
    out = mic.splice_into_module(
        "base\n",
        _translation("export function map_item(i){ return helperFn(i); }",
                     helpers=["function helperFn(x){ return x; }"]),
        "datasources/x/search_x.py",
    )
    assert "function helperFn(x)" in out
    assert "export function map_item" in out


def test_splice_partial_markers_refuses():
    start = mic.BLOCK_MARKER_START
    existing = f"x\n{start}\nonly start, no end\n"
    with pytest.raises(ValueError):
        mic.splice_into_module(
            existing, _translation("function map_item(){}"), "datasources/x/search_x.py"
        )


def test_splice_dedups_existing_imports():
    imp = "import { foo } from './other.js';"
    out = mic.splice_into_module(
        f"{imp}\nconst a = 1;\n",
        _translation("export function map_item(i){ return foo(i); }", imports=[imp]),
        "datasources/x/search_x.py",
    )
    # the import already exists outside any marker block, so it must not be re-added
    assert out.count(imp) == 1


# --------------------------------------------------------------------------- #
# _strip_js_comments (C3) and lint_translation
# --------------------------------------------------------------------------- #

def test_strip_js_comments_preserves_url_in_string():
    """C3: the `//` in a URL string literal must survive (the old naive regex
    truncated `"https://x"` to `"https:` and produced bogus lint warnings)."""
    out = mic._strip_js_comments('const u = "https://example.com/p"; // real comment')
    assert "https://example.com/p" in out
    assert "real comment" not in out


def test_strip_js_comments_removes_block_and_line_comments():
    assert mic._strip_js_comments("a /* x */ b") == "a  b"
    assert mic._strip_js_comments("keep // drop").rstrip() == "keep"


def test_lint_no_false_newline_warning_on_url():
    """C3 follow-through: a URL string must not be flagged as a literal newline."""
    issues = mic.lint_translation(
        _translation('function map_item(i){ return "https://x/y"; }')
    )
    assert not any("newline" in i.lower() for i in issues)


def test_lint_flags_dict_get_with_caveat():
    """C5: `.get(` is flagged, and the message carries the JS-Map false-positive
    caveat (decoupled from the prompt rule)."""
    issues = mic.lint_translation(
        _translation("function map_item(i){ return i.get('a'); }")
    )
    assert any(".get(" in i for i in issues)
    assert any("Map" in i for i in issues)  # caveat present


def test_lint_flags_missing_new():
    issues = mic.lint_translation(
        _translation("function map_item(i){ return MappedItem({a: 1}); }")
    )
    assert any("without" in i and "new" in i for i in issues)


def test_lint_flags_literal_newline_in_string():
    issues = mic.lint_translation(
        _translation('function map_item(i){ return i.x.join("\n"); }')  # real newline
    )
    assert any("newline" in i.lower() for i in issues)


def test_lint_flags_regex_use():
    issues = mic.lint_translation(
        _translation(r"function map_item(i){ return i.text.match(/\w+/); }")
    )
    assert any("regex" in i.lower() for i in issues)


def test_lint_clean_translation_has_no_issues():
    issues = mic.lint_translation(
        _translation("export function map_item(i){ return new MappedItem({id: i['id'] ?? null}); }")
    )
    assert issues == []


# --------------------------------------------------------------------------- #
# rules registry wiring
# --------------------------------------------------------------------------- #

def test_regex_lint_rules_use_lint_message_when_set():
    # dict_get carries a separate lint_message (mentions Map), distinct from its
    # prompt_rule, and that is what the lint pass surfaces.
    get_msg = next(
        msg for pat, msg in rules.get_regex_lint_rules()
        if pat.pattern == r"\.get\("
    )
    assert "Map" in get_msg
    dict_get_rule = next(r for r in rules.RULES if r.id == "dict_get")
    assert get_msg == dict_get_rule.lint_message
    assert get_msg != dict_get_rule.prompt_rule


# --------------------------------------------------------------------------- #
# plan_matrix — including the S1 injection-rejection guarantee
# --------------------------------------------------------------------------- #

def test_plan_matrix_bootstrap():
    mode, matrix, rejected = ci.plan_matrix("workflow_dispatch", "", True, "", "")
    assert mode == "bootstrap"
    assert matrix == [{"module": "bootstrap", "files": "", "bootstrap": True}]
    assert rejected == []


def test_plan_matrix_explicit_files_override_bootstrap():
    mode, matrix, _ = ci.plan_matrix(
        "workflow_dispatch", "datasources/tiktok/search_tiktok.py", True, "", ""
    )
    assert mode == "files"  # files win over bootstrap
    assert [m["module"] for m in matrix] == ["tiktok"]


def test_plan_matrix_groups_by_module_sorted():
    mode, matrix, rejected = ci.plan_matrix(
        "workflow_dispatch",
        "datasources/tiktok/search_tiktok.py datasources/gab/search_gab.py",
        False, "", "",
    )
    assert mode == "files"
    assert [m["module"] for m in matrix] == ["gab", "tiktok"]
    assert rejected == []


def test_plan_matrix_push_uses_injected_git_diff():
    changed = ["datasources/tiktok/search_tiktok.py", "datasources/tiktok/search_other.py"]
    mode, matrix, _ = ci.plan_matrix(
        "push", "", False, "aaaaaaa", "bbbbbbb", git_diff=lambda b, a: changed
    )
    assert mode == "files"
    assert len(matrix) == 1 and matrix[0]["module"] == "tiktok"
    assert "search_tiktok.py" in matrix[0]["files"]
    assert "search_other.py" in matrix[0]["files"]


def test_plan_matrix_none_when_no_changes():
    mode, matrix, rejected = ci.plan_matrix(
        "push", "", False, "a", "b", git_diff=lambda b, a: []
    )
    assert mode == "none" and matrix == [] and rejected == []


def test_plan_matrix_rejects_shell_injection_paths():
    """S1: paths with shell metacharacters (or otherwise not matching the strict
    datasource shape) are dropped and reported, never placed in the matrix that
    gets interpolated into the sync job's shell command."""
    candidates = (
        "datasources/x/search_$(id).py "        # command substitution
        "datasources/x/search_x.py;whoami "      # command separator
        "../../etc/passwd "                       # traversal
        "datasources/ok/search_ok.py"            # the only valid one
    )
    mode, matrix, rejected = ci.plan_matrix(
        "workflow_dispatch", candidates, False, "", ""
    )
    all_files = " ".join(m["files"] for m in matrix)
    assert "datasources/ok/search_ok.py" in all_files
    assert "$(id)" not in all_files
    assert ";" not in all_files
    assert ".." not in all_files
    assert len(rejected) == 3
    assert [m["module"] for m in matrix] == ["ok"]


# --------------------------------------------------------------------------- #
# build_pr_body
# --------------------------------------------------------------------------- #

def test_build_pr_body_single_module_title_and_warnings():
    manifest = {
        "model": "qwen2.5-coder:14b", "provider": "ollama",
        "total_duration_seconds": 12.3,
        "entries": [{
            "python_file": "datasources/tiktok/search_tiktok.py",
            "js_file": "modules/tiktok.js", "status": "ok", "duration_seconds": 5.0,
            "commentary": "a note", "lint_warnings": ["[map_item_function] .get( found"],
        }],
    }
    title, body = ci.build_pr_body(
        manifest, module="tiktok", is_bootstrap=False, before="a" * 7, after="b" * 7,
        run_id="42", event_name="workflow_dispatch", repo="org/4cat",
    )
    assert title == "Auto-translated map_item updates from 4CAT: tiktok"
    assert "Lint warnings — fix before merging" in body
    assert "modules/tiktok.js" in body
    assert "qwen2.5-coder:14b" in body


def test_build_pr_body_bootstrap_title_counts_modules():
    manifest = {"entries": [
        {"python_file": "datasources/a/search_a.py", "js_file": "modules/a.js", "status": "ok"},
        {"python_file": "datasources/b/search_b.py", "js_file": "modules/b.js", "status": "ok"},
    ]}
    title, _ = ci.build_pr_body(
        manifest, module="bootstrap", is_bootstrap=True, before="", after="",
        run_id="1", event_name="workflow_dispatch", repo="org/4cat",
    )
    assert title == "Auto-translated map_item updates from 4CAT (bootstrap, 2 datasources)"


def test_build_pr_body_push_invokes_injected_diff():
    manifest = {"entries": [{
        "python_file": "datasources/a/search_a.py", "js_file": "modules/a.js", "status": "ok",
    }]}
    calls = []

    def fake_diff(before, after, path):
        calls.append((before, after, path))
        return "diff --git a/x b/x\n+added"

    _, body = ci.build_pr_body(
        manifest, module="a", is_bootstrap=False, before="X", after="Y",
        run_id="1", event_name="push", repo="org/4cat", python_diff=fake_diff,
    )
    assert calls == [("X", "Y", "datasources/a/search_a.py")]
    assert "<details><summary>Python diff</summary>" in body
    assert "+added" in body


# --------------------------------------------------------------------------- #
# set_output — S2 (GITHUB_OUTPUT injection-safe)
# --------------------------------------------------------------------------- #

def test_set_output_uses_delimiter_form(tmp_path, monkeypatch):
    out_file = tmp_path / "gh_output"
    out_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(out_file))

    # a value containing a newline + an "=" line that would forge an extra
    # output in the naive `name=value` form
    ci.set_output("title", "Real Title\nmalicious=pwned")

    content = out_file.read_text(encoding="utf-8")
    assert content.startswith("title<<")          # delimiter form, not `title=`
    assert "Real Title\nmalicious=pwned" in content  # value preserved verbatim
    # the injected line is inside the heredoc body, not a standalone output line
    assert not content.startswith("title=")


def test_set_output_noop_without_env(monkeypatch):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    # must not raise when not running under Actions
    ci.set_output("title", "anything")


# --------------------------------------------------------------------------- #
# splice — refuse to duplicate a pre-existing map_item on first sync (review #2)
# --------------------------------------------------------------------------- #

def test_splice_refuses_preexisting_map_item_without_markers():
    """First sync (no markers) must NOT append a second `map_item` when the
    module already declares one — that would be a JS redeclaration error."""
    existing = "export function map_item(item) { return item; }\n"
    with pytest.raises(ValueError):
        mic.splice_into_module(
            existing,
            _translation("export function map_item(i){ return new MappedItem({}); }"),
            "datasources/x/search_x.py",
        )


def test_splice_refuses_preexisting_const_map_item():
    existing = "const map_item = (item) => item;\n"
    with pytest.raises(ValueError):
        mic.splice_into_module(
            existing,
            _translation("export function map_item(i){ return new MappedItem({}); }"),
            "datasources/x/search_x.py",
        )


def test_splice_allows_commented_map_item_without_markers():
    """A `map_item` declaration that exists only inside a comment must not trip
    the guard (comments are stripped before the check)."""
    existing = "// old: export function map_item(item) {}  (removed)\nconst a = 1;\n"
    out = mic.splice_into_module(
        existing,
        _translation("export function map_item(i){ return new MappedItem({}); }"),
        "datasources/x/search_x.py",
    )
    assert mic.BLOCK_MARKER_START in out


# --------------------------------------------------------------------------- #
# _code_fence — PR-body diff can't be closed early by its own backticks (#5)
# --------------------------------------------------------------------------- #

def test_code_fence_default_three_backticks():
    assert ci._code_fence("no backticks here", "diff") == ("```diff", "```")


def test_code_fence_grows_past_inner_backticks():
    # longest run inside is 4 backticks -> fence must be 5
    open_f, close_f = ci._code_fence("a ``` b ```` c", "diff")
    assert open_f == "`````diff"
    assert close_f == "`````"


def test_build_pr_body_diff_fence_survives_backticks():
    manifest = {"entries": [{
        "python_file": "datasources/a/search_a.py", "js_file": "modules/a.js", "status": "ok",
    }]}

    def fake_diff(before, after, path):
        # a Python diff whose body itself contains a ``` fence
        return "diff --git a/x b/x\n+doc = '''\n+```\n+'''"

    _, body = ci.build_pr_body(
        manifest, module="a", is_bootstrap=False, before="X", after="Y",
        run_id="1", event_name="push", repo="org/4cat", python_diff=fake_diff,
    )
    # outer fence is longer than the inner ``` so the block isn't closed early
    assert "````diff" in body


# --------------------------------------------------------------------------- #
# extract_llm_requirements — single source of truth from setup.py (review #3)
# --------------------------------------------------------------------------- #

def test_extract_llm_requirements_filters_and_preserves_specifiers():
    setup_py = '''
core_packages = {
    "Flask~=3.0",
    "langchain_core",
    "langchain_ollama",
    "pydantic",
    "requests~=2.27",
    "requests_futures",
    "ruff",
}
processor_packages = {
    "numpy",
    "beautifulsoup4",
}
'''
    reqs = ci.extract_llm_requirements(setup_py)
    assert "langchain_core" in reqs
    assert "langchain_ollama" in reqs
    assert "pydantic" in reqs
    assert "requests~=2.27" in reqs          # version specifier preserved verbatim
    assert "requests_futures" not in reqs    # name-equality, not substring match
    assert "Flask~=3.0" not in reqs
    assert "ruff" not in reqs
    assert reqs == sorted(reqs)              # output is sorted
