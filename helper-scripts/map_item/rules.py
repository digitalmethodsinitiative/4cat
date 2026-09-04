"""
Registry of known Python → JavaScript translation pitfalls for the
Zeeschuimer auto-generator.

Each `TranslationError` record drives three things in
`map_item/converter.py`:

- The "things to get right" section of the LLM prompt.
- The "before submitting" verification checklist.
- The regex-based lint pass over LLM output.

Cross-repo workflow:

- `translation-errors.md` (in the Zeeschuimer repo) is the freeform
  observation log. Reviewers add entries there as new bugs surface.
- This file is the structured input for the prompt and linter. When an
  observation in the md is worth teaching the generator about, mirror it
  here using the same `id` as the md heading slug. Not every md entry
  needs a record — this is a curated subset.

Three lint checks are too complex for a single regex and live as bespoke
code in `converter.lint_translation`:

- `class_needs_new` — variable-width lookbehind for `new `.
- `literal_newline_in_string` — JS string lexer.
- `regex_in_use` — heuristic regex-use detection.

Those records have `lint_pattern=None`; the bespoke check is the lint.

Some records have `lint_pattern=None` and no check behind them either, because
nothing here can catch them:

- `python_file_helpers` and `undefined_identifier` are about what the finished
  module ends up containing, not about the translation on its own. Each piece
  of a translation can be valid JavaScript while the module they are spliced
  into refers to something nobody defined. Comparing what the generated code
  uses against what it defines is a job for a JavaScript linter, and it is
  planned for Zeeschuimer, where the globals sit next to the file that
  declares them.
- A regex for `python-or-vs-js-falsy-vs-nullish` or for
  `-swallowing-a-deliberate-null` would have to flag `??`, which is also
  correct in `?? null`, `?? ''` and `?? new MissingMappedField(...)`, so it is
  everywhere in this output.

For those, the prompt and the checklist are the whole of it.
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TranslationError:
    id: str
    prompt_rule: str
    bad: Optional[str] = None
    good: Optional[str] = None
    verify: Optional[str] = None
    lint_pattern: Optional[re.Pattern] = None
    # Message surfaced on the PR when `lint_pattern` matches. Defaults to
    # `prompt_rule`; set it separately when the regex is heuristic and can
    # false-positive, so the reviewer-facing warning can carry that caveat
    # without bloating the LLM prompt.
    lint_message: Optional[str] = None


RULES: list[TranslationError] = [

    # ---- Everything map_item uses has to exist ----

    TranslationError(
        id="python_file_helpers",
        prompt_rule=(
            "`map_item` is never the whole of what you have to translate. It leans on "
            "other things defined elsewhere in the same Python file, and every one of "
            "those it uses becomes an entry in `helpers_to_add`. There are three "
            "kinds, and all three have been dropped before: module-level functions "
            "written outside the class (douyin's `defined`, `stream_link`, "
            "`first_link`, `absolute_link`, `download_prevented`), `@staticmethod` "
            "helpers on the class (`get_chinese_number`, `get_centroid`, "
            "`_screen_name_from_media`, `extract_hashtags`), and class constants "
            "(`MEDIA_TYPE_PHOTO`, `HASHTAG_REGEX`). Read the whole file, not just "
            "`map_item`. Functions become `function`s and constants become `const`s, "
            "and the class prefix goes: Python `SearchDouyin.get_chinese_number(n)` "
            "becomes `getChineseNumber(n)`. Only ever write that call if you also "
            "emitted the function. Ignore the class's own settings — `type`, "
            "`category`, `title`, `description`, `extension`, `references` and the "
            "like are 4CAT bookkeeping and mean nothing in JavaScript."
        ),
        bad=(
            "map_item_function: `count: getChineseNumber(stats['user_count_str'])`\n"
            "helpers_to_add: []   // the function was never emitted"
        ),
        good=(
            "map_item_function: `count: getChineseNumber(stats['user_count_str'])`\n"
            "helpers_to_add: ['function getChineseNumber(num) { ... }']"
        ),
        verify=(
            "Every module-level function, `@staticmethod` and class constant that "
            "`map_item` uses has a matching entry in `helpers_to_add`."
        ),
        # Nothing here can catch this: it only shows up once the translation
        # has been spliced into the module. Prompt and checklist only.
        lint_pattern=None,
    ),
    TranslationError(
        id="undefined_identifier",
        prompt_rule=(
            "Every name `map_item_function` uses must exist somewhere: declared "
            "inside the function itself, emitted in `helpers_to_add`, on the "
            "Zeeschuimer globals list above, or provided by JavaScript itself. "
            "Nothing else is available — the module keeps only what you return, so "
            "anything you leave out is gone, including a helper that was in the "
            "module before. A name with nothing behind it is not a warning you can "
            "leave for the reviewer: the module throws on its first item and the "
            "whole datasource maps nothing."
        ),
        verify=(
            "Every name used in `map_item_function` is declared in it, listed in "
            "`helpers_to_add`, a Zeeschuimer global, or a JavaScript built-in."
        ),
        # Nothing here can catch this: it only shows up once the translation
        # has been spliced into the module. Prompt and checklist only.
        lint_pattern=None,
    ),

    # ---- Python syntax that does not exist in JavaScript ----

    TranslationError(
        id="python_keywords",
        prompt_rule=(
            "Python keywords don't exist in JavaScript: `None` → `null`, "
            "`True` / `False` → `true` / `false` (lowercase), `def name(...)` → `function name(...)`."
        ),
        bad="return None if not item.is_admin else True",
        good="return item.is_admin ? true : null",
        verify="No Python keywords (`None`, `True`, `False`, `def`) appear.",
        lint_pattern=re.compile(r"\b(?:None|True|False)\b|\bdef\s+\w+\s*\("),
    ),
    TranslationError(
        id="python_fstring",
        prompt_rule=(
            "Python f-strings (`f\"...\"` / `f'...'`) don't exist in JavaScript. Use "
            "template literals with backticks and `${...}` instead."
        ),
        bad='throw new Error(f"item {item.id} not found")',
        good="throw new Error(`item ${item.id} not found`)",
        lint_pattern=re.compile(r"\bf\"|\bf'"),
    ),
    TranslationError(
        id="unquoted_interpolation",
        prompt_rule=(
            "Even without an `f` prefix, `\"text {var}\"` / `'text {var}'` are literal "
            "text in JavaScript — no interpolation happens. Whenever the original Python "
            "used an f-string, the JS must use a template literal (backticks)."
        ),
        bad="throw new MapItemException('different user {user.id} and owner {owner.id}')",
        good="throw new MapItemException(`different user ${user.id} and owner ${owner.id}`)",
        verify="No `{var}` patterns remain inside single- or double-quoted strings.",
        lint_pattern=re.compile(r"""['"][^'"\n]*\{[a-zA-Z_$][\w$.]*\}[^'"\n]*['"]"""),
    ),
    TranslationError(
        id="python_from_import",
        prompt_rule=(
            "Python `from X import Y` doesn't exist in JavaScript. JavaScript uses "
            "`import { Y } from 'X'` — and only when really needed; Zeeschuimer helpers "
            "are globals, so `imports_to_add` is usually empty."
        ),
        bad="from common.lib.helpers import strip_tags",
        good="// (no import — strip_tags is a global from js/lib.js)",
        lint_pattern=re.compile(r"^\s*from\s+\S+\s+import\b", re.MULTILINE),
    ),

    # ---- dict.get is not a thing in JS ----

    TranslationError(
        id="dict_get",
        prompt_rule=(
            "Python `dict.get(k)` / `dict.get(k, default)` does not exist in "
            "JavaScript. Both forms become the global `py_get` listed above: "
            "`d.get(k)` is `py_get(d, k)` and `d.get(k, default)` is "
            "`py_get(d, k, default)`, which hands back the default only when the "
            "key is absent, exactly as Python does. Do NOT write `d[k] ?? default` "
            "for a `.get`: that also replaces a key the source did send as null, "
            "which Python keeps. Bare `d[k]` is fine where the value is only "
            "tested or passed straight on, but as a field of the mapped item it "
            "gives `undefined`, and the key then disappears from the output."
        ),
        bad=(
            "user.get('name', 'anonymous')    // Python, not JavaScript\n"
            "user['name'] ?? 'anonymous'      // replaces a real null as well"
        ),
        good="py_get(user, 'name', 'anonymous')",
        verify=(
            "The function contains zero `.get(` calls, and every Python "
            "`.get(k, default)` became `py_get(d, k, default)`."
        ),
        lint_pattern=re.compile(r"\.get\("),
        lint_message=(
            "`.get(` call found. Python `dict.get(k[, default])` does not exist "
            "in JavaScript — use the `py_get` global. NOTE: this check is a "
            "plain substring match, so it also flags legitimate JS `.get()` on "
            "`Map`, `URLSearchParams`, `Headers`, etc. — ignore the warning if "
            "the receiver is one of those."
        ),
    ),

    # ---- Falling back on a missing value: `||` and `??` are not the same ----

    TranslationError(
        id="python-or-vs-js-falsy-vs-nullish",
        prompt_rule=(
            "Python `a or b` falls back on ANY falsy left side: `None`, `''`, `0`, "
            "`False`, `[]`, `{}`. JavaScript `a ?? b` falls back ONLY on `null` and "
            "`undefined`, so an empty string or a zero on the left is kept and the "
            "fallback never runs. Translate Python `or` as JavaScript `||`, which "
            "falls back on the same values Python does. Save `??` for an explicit "
            "Python `is not None` test. Both examples below broke real output: X "
            "carries an empty string in its newer `core` / `avatar` / `banner` "
            "objects while the real value is still in `legacy`, so `??` blanked "
            "the author name, full name and avatar and left the post link pointing "
            "at `/i/web/status/<id>`; Instagram sends an empty-string author id, "
            "so `??` returns that instead of falling through to `pk`. A "
            "`dict.get(k, default)` is not an `or` and takes neither operator "
            "— it is `py_get(d, k, default)`."
        ),
        bad=(
            "core['screen_name'] ?? legacy['screen_name'] ?? ''   // twitter map_user\n"
            "author['id'] ?? author['pk']                         // instagram get_author_id"
        ),
        good=(
            "core['screen_name'] || legacy['screen_name'] || ''\n"
            "author['id'] || author['pk']"
        ),
        verify=(
            "Every fallback that Python wrote with `or` uses `||`; `??` appears "
            "only where Python tested for null."
        ),
        # A regex flagging every `??` would bury the real cases: `?? null`,
        # `?? ''` and `?? new MissingMappedField(...)` are all correct and are
        # everywhere in this output. Prompt and checklist guidance only.
        lint_pattern=None,
    ),
    TranslationError(
        id="-swallowing-a-deliberate-null",
        prompt_rule=(
            "The mirror image of the rule above, and it bites even where the "
            "Python has no `or` in it at all. `??` is not a general-purpose "
            "fallback operator; it translates one specific Python idiom, an "
            "explicit test for null. Python's `dict.get(key, default)` hands back "
            "the default ONLY when the key is absent, so a key that is present and "
            "null gives null. `data?.[key] ?? default` collapses those two cases "
            "and turns a null the platform deliberately sent into the fallback. "
            "Use `py_get` for a `.get`, and reach for `??` only where the Python "
            "itself asked whether the value was null."
        ),
        bad=(
            "function defined(data, key, defaultValue = null) {\n"
            "    const value = data?.[key] ?? defaultValue;  // present null -> default\n"
            "    return value === '$undefined' ? defaultValue : value;\n"
            "}"
        ),
        good=(
            "function defined(data, key, defaultValue = null) {\n"
            "    const value = py_get(data, key, defaultValue);\n"
            "    return value === '$undefined' ? defaultValue : value;\n"
            "}"
        ),
        verify=(
            "No `??` stands in for a Python `dict.get(k, default)` — those are "
            "`py_get(d, k, default)`."
        ),
        # Linting this means linting `??`, which the record above already
        # explains is far too common in correct output to flag. The two records
        # are one misuse seen from either side, so they get the same treatment:
        # prompt and checklist guidance only.
        lint_pattern=None,
    ),

    # ---- `in` operator: substring check vs key existence ----

    TranslationError(
        id="in_operator_on_strings",
        prompt_rule=(
            "Python `'x' in some_string` is a substring check. JavaScript's `in` operator "
            "only works on objects (checking property names) — on a string it throws "
            "TypeError. Use `someString.includes('x')` instead."
        ),
        bad="if ('polaris' in item.__typename.toLowerCase()) { ... }",
        good="if (item.__typename.toLowerCase().includes('polaris')) { ... }",
        verify="No `'literal' in someStringExpression` — use `.includes(...)`.",
        # Conservative: only flag when the RHS ends in a known string method, since
        # `'key' in someObj` is legitimate JS for property checks.
        lint_pattern=re.compile(
            r"""['"][^'"]*['"]\s+in\s+[\w.\[\]]+\.(?:"""
            r"""toLowerCase|toUpperCase|toString|trim|trimStart|trimEnd|"""
            r"""slice|substring|substr|concat|charAt|normalize|repeat|"""
            r"""padStart|padEnd|replace|replaceAll)\s*\("""
        ),
    ),
    TranslationError(
        id="key_existence_vs_value_truthy",
        prompt_rule=(
            "Python `if node.get('X'):` is a *truthy check on the value* (false if the key "
            "is missing OR if the value is `None`/empty). The naive translation "
            "`if ('X' in node)` is a *key existence check* — true even when `node.X` is "
            "`null`. Subsequent property accesses then throw. Use `if (node.X)` or "
            "`if (node.X != null)`."
        ),
        bad="const usertags = 'usertags' in node ? node.usertags.in.map(...) : '';",
        good="const usertags = node.usertags ? node.usertags.in.map(...) : '';",
        lint_pattern=re.compile(r"'[^']+'\s+in\s+[a-zA-Z_$][\w$]*\s*\?"),
    ),

    # ---- Empty container is truthy in JS ----

    TranslationError(
        id="empty_container_truthy",
        prompt_rule=(
            "Empty `{}` and `[]` are TRUTHY in JavaScript but FALSY in Python. After "
            "`const user = node.user ?? {}`, `if (user)` is always true. Either guard on "
            "the original nullable BEFORE defaulting, or check `Object.keys(user).length` "
            "/ `arr.length`."
        ),
        bad="const user = node.user ?? {};\nif (user) { /* always true */ }",
        good="const user = node.user;\nif (user) { /* meaningful */ }",
        verify="No `if (x)` guards where `x` was defaulted to `{}` or `[]` (always true in JS).",
    ),
    TranslationError(
        id="empty-collections-are-falsy-in-python-truthy-in-javascript",
        prompt_rule=(
            "The same difference bites without any default being added. Python "
            "counts `[]`, `{}`, `''` and `0` as false; JavaScript counts only `''` "
            "and `0`, so an empty array or object is TRUE there. `if some_list:` "
            "and `if (someList)` therefore take opposite branches on an empty "
            "list, and the JavaScript walks into the branch that reads "
            "`someList[0]` and throws. Write a Python truthy test on a list as "
            "`Array.isArray(x) && x.length`, and on an object as "
            "`Object.keys(x).length`. `if not some_list:` is the same bug "
            "mirrored: Python takes the 'nothing here' branch for `[]` and "
            "`if (!someList)` does not."
        ),
        bad=(
            "const videos_list = item['video']?.['bitRateList'];\n"
            "if (videos_list) {                     // [] is true in JavaScript\n"
            "    video_url = videos[0]['playApi'];  // TypeError on an empty list\n"
            "}"
        ),
        good=(
            "const videos_list = item['video']?.['bitRateList'];\n"
            "if (Array.isArray(videos_list) && videos_list.length) {\n"
            "    video_url = videos[0]['playApi'];\n"
            "}"
        ),
        verify=(
            "Every truthy test on a list or an object checks its contents "
            "(`Array.isArray(x) && x.length`, `Object.keys(x).length`) rather than "
            "the value itself."
        ),
        # Goes by the shape of the guard, since nothing here can know the type:
        # a bare truthy test on something *named* like a collection. Over the
        # twelve generated blocks currently in Zeeschuimer it flags two lines,
        # both of them this bug. Names that read as booleans (`isX`, `hasX`) are
        # excluded, which is what the one false positive there looked like.
        lint_pattern=re.compile(
            r"if\s*\(\s*!?(?!(?:is|has)[A-Z])[a-zA-Z_$][A-Za-z0-9_$]*"
            r"(?:[Ll]ist|s)\s*\)"
        ),
        lint_message=(
            "Bare truthy check on a name that looks like a collection. An empty "
            "`[]` or `{}` is false in Python and true in JavaScript, so this takes "
            "the opposite branch on an empty list, and the code inside then "
            "indexes element `[0]` of it. Use `Array.isArray(x) && x.length` (or "
            "`Object.keys(x).length`). NOTE: the check goes by the name, so a "
            "plural holding a string or a boolean is a false positive — ignore "
            "the warning if the value is not a list or an object."
        ),
    ),

    # ---- Object identity ----

    TranslationError(
        id="class_needs_new",
        prompt_rule=(
            "`MappedItem`, `MissingMappedField`, and `MapItemException` are CLASSES — "
            "always `new MappedItem({...})`, `new MissingMappedField(...)`, "
            "`throw new MapItemException(...)`. Calling them bare returns `undefined` "
            "and silently breaks downstream."
        ),
        bad="return MappedItem({author: 'foo'})",
        good="return new MappedItem({author: 'foo'})",
        verify="Every `MappedItem(`, `MissingMappedField(`, and `MapItemException(` is preceded by `new`.",
        # Bespoke check in `lint_translation` (variable-width lookbehind).
        lint_pattern=None,
    ),
    TranslationError(
        id="object_reference_equality",
        prompt_rule=(
            "`!==` / `===` on objects compares references, not values. "
            "`caption !== new MissingMappedField('')` is always true because `new` "
            "creates a fresh object each call. Use `instanceof MissingMappedField` for "
            "type checks, or truthy-check the value directly."
        ),
        bad="caption !== new MissingMappedField('') ? caption.match(...) : ''",
        good="caption instanceof MissingMappedField ? '' : caption.match(...)",
        lint_pattern=re.compile(r"(?:!==|===)\s+new\s+[A-Z]"),
    ),

    # ---- Method calls on possibly-null receivers ----

    TranslationError(
        id="method_chain_on_nullable",
        prompt_rule=(
            "Calling a method on `null` / `undefined` throws TypeError. In Python the "
            "equivalent AttributeError is sometimes caught by 4CAT — but the JS "
            "`map_item` doesn't catch. Use optional chaining (`?.`) whenever the "
            "receiver could be null/undefined."
        ),
        bad="caption.match(/#(\\w+)/g).join(',')",
        good="caption?.match(/#(\\w+)/g)?.join(',') ?? ''",
        # No reliable static check — leave to reviewer.
        lint_pattern=None,
    ),

    # ---- Datetime: use the global helper ----

    TranslationError(
        id="datetime_helper_preferred",
        prompt_rule=(
            "For Python `datetime.utcfromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S')`, "
            "use the global `formatUtcTimestamp(t)` helper from `js/lib.js` — NOT "
            "`new Date(t * 1000).toISOString()`. `.toISOString()` produces "
            "`2026-05-13T21:27:31.000Z` (T separator, milliseconds, Z), which doesn't "
            "match the Python output `2026-05-13 21:27:31`."
        ),
        bad="collected_at: new Date(node.taken_at * 1000).toISOString()",
        good="collected_at: formatUtcTimestamp(node.taken_at)",
        lint_pattern=re.compile(r"new\s+Date\([^)]+\)\.toISOString\(\)"),
    ),

    # ---- Regex translation traps ----

    TranslationError(
        id="regex_findall_capture_groups",
        prompt_rule=(
            "Python `re.findall(r'#(\\w+)', s)` returns CAPTURE GROUP contents "
            "(`['lotr']`). JavaScript `s.match(/#(\\w+)/g)` returns FULL MATCHES "
            "(`['#lotr']`) — capture groups are ignored with `/g`. For capture-group "
            "behavior use `[...s.matchAll(/.../g)].map(m => m[1])`, or post-process the "
            "full matches to strip the literal prefix."
        ),
        bad="caption.match(/#(\\w+)/g)?.join(',')",
        good="[...caption.matchAll(/#(\\w+)/g)].map(m => m[1]).join(',')",
        lint_pattern=re.compile(r"\.match\(\s*/[^/]*\([^/]*\)[^/]*/g\s*\)"),
    ),
    TranslationError(
        id="regex_in_use",
        prompt_rule=(
            "Regex translation between Python and JavaScript is fragile: flag syntax "
            "differs (`re.IGNORECASE` → `/.../i`), Python `re.compile(p).search(s)` "
            "becomes JS `s.match(p)` or `new RegExp(p).exec(s)`, and regex literals "
            "cannot span lines — encode any literal newline as `\\n`. Translate "
            "carefully and verify behavior end-to-end."
        ),
        # Bespoke check in `lint_translation` flags any regex use for human review.
        lint_pattern=None,
    ),

    # ---- String/regex literal syntax ----

    TranslationError(
        id="literal_newline_in_string",
        prompt_rule=(
            "JavaScript single- or double-quoted strings cannot contain a literal "
            "newline — syntax error. Python `\"\\n\".join(xs)` becomes JS "
            "`xs.join(\"\\n\")` — keep `\\n` as an escape sequence; never put a real "
            "newline inside the quotes. Template literals (backticks) may span lines."
        ),
        bad='lines.join("\n")  // raw newline = syntax error',
        good='lines.join("\\n")',
        verify="No string or regex literal contains a raw newline character — use `\\n`.",
        # Bespoke check in `lint_translation` (JS string lexer).
        lint_pattern=None,
    ),

    # ---- Imports: don't, unless you really must ----

    TranslationError(
        id="lib_js_import",
        prompt_rule=(
            "`js/lib.js` is loaded as a plain `<script>`, NOT an ES module. Its "
            "declarations (`MappedItem`, `MissingMappedField`, `MapItemException`, "
            "`strip_tags`, `normalize_url_encoding`, `formatUtcTimestamp`) are GLOBALS. "
            "Never write `import { ... } from '../js/lib.js'` — that import fails at "
            "runtime."
        ),
        bad="import { MappedItem } from '../js/lib.js';",
        good="// (no import — MappedItem is global)",
        verify="`imports_to_add` is empty unless you really need an ES-module import (NOT for `MappedItem` etc.).",
        lint_pattern=re.compile(
            r"""import\s*(?:\{[^}]*\}|\*\s+as\s+\w+|\w+)\s+from\s+['"]\.\.?/js/lib\.js['"]"""
        ),
    ),
    TranslationError(
        id="bare_relative_path_import",
        prompt_rule=(
            "Every entry in `imports_to_add` must be a complete `import { ... } from '...'` "
            "statement. Never emit a bare relative path (like `'../js/lib.js'`) as an "
            "entry — JavaScript parses that as `..` `.` `/js/lib.js` and rejects the file."
        ),
        bad="imports_to_add: ['../js/lib.js']",
        good="imports_to_add: []  // helpers are globals; no import needed",
        # Surfaces in `imports_to_add`, not in the function body — not lint-able by
        # the regex pass over `map_item_function`.
        lint_pattern=None,
    ),

    # ---- JSON serialization difference ----

    TranslationError(
        id="undefined_dropped_from_json",
        prompt_rule=(
            "`JSON.stringify` omits keys whose value is `undefined`. Python's "
            "`json.dumps` serializes `None` as `null`, keeping the key. When the Python "
            "`map_item` explicitly returns `None` (or `\"\"`) for a missing field, the "
            "JS must explicitly assign `null` (or `\"\"`) — typically with `value ?? null` "
            "or `value ?? \"\"`, matching whichever Python uses for that field."
        ),
        bad="location_city: node.location.city  // undefined → key disappears from output",
        good="location_city: node.location.city ?? null  // matches Python's `None`",
        # Hard to lint statically (depends on per-field Python behavior).
        lint_pattern=None,
    ),
]


def get_regex_lint_rules() -> list[tuple[re.Pattern, str]]:
    """
    Return all (pattern, message) pairs for the regex-based lint pass. The
    message is the rule's `lint_message` when set, else its `prompt_rule`.

    Bespoke lint checks (class instantiation, literal newlines, regex use)
    are NOT included here — they live in `converter.lint_translation`
    and are tied to records by `id` in comments.
    """
    return [
        (r.lint_pattern, r.lint_message or r.prompt_rule)
        for r in RULES
        if r.lint_pattern is not None
    ]
