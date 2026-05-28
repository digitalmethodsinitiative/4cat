"""
Registry of known Python → JavaScript translation pitfalls for the
Zeeschuimer auto-generator.

Each `TranslationError` record drives three things in
`map_item_converter.py`:

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
code in `map_item_converter.lint_translation`:

- `class_needs_new` — variable-width lookbehind for `new `.
- `literal_newline_in_string` — JS string lexer.
- `regex_in_use` — heuristic regex-use detection.

Those records have `lint_pattern=None`; the bespoke check is the lint.
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


RULES: list[TranslationError] = [

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
            "Python `dict.get(k)` / `dict.get(k, default)` does not exist in JavaScript. "
            "Replace every `.get(k)` with `[k]` and every `.get(k, default)` with `[k] ?? default`."
        ),
        bad="user.get('name', 'anonymous')",
        good="user['name'] ?? 'anonymous'",
        verify="The function contains zero `.get(` calls.",
        lint_pattern=re.compile(r"\.get\("),
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
    Return all (pattern, message) pairs for the regex-based lint pass.

    Bespoke lint checks (class instantiation, literal newlines, regex use)
    are NOT included here — they live in `map_item_converter.lint_translation`
    and are tied to records by `id` in comments.
    """
    return [(r.lint_pattern, r.prompt_rule) for r in RULES if r.lint_pattern is not None]
