"""
Declarative processor compatibility.

A processor says what it accepts as a `Compatibility` -- the dataset type, file
extension, media type, datasource, columns it needs, and the settings/executables its
environment needs. `Compatibility.check(subject)` compares that against a `subject`,
which is one of two things:

* a live dataset (wrapped in `DatasetShape`), when 4CAT decides at run time whether a
  processor can run on a dataset;
* a processor's declared output (a `Shape`, built in outputs.py from its `Output`),
  when the processor map works out which processors can follow which without running
  anything.

Both answer the same handful of questions -- extension, media, columns, and so on --
each a real value or `UNKNOWN` when a declared output has not pinned it down. `check`
returns "yes", "no" or "maybe": a live dataset knows all its values so the answer is
only ever yes/no, but a declared output can leave things open, which is where "maybe"
comes from. There is one comparison, written once, so the run-time check and the map
can never disagree.

A processor whose acceptance can't be expressed this way (e.g. it must walk a dataset's
ancestry) keeps a custom `is_compatible_with` method instead; that wins at run time.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from functools import cached_property
from typing import Iterable, Optional


# Marks a property a declared output has not pinned down (a filter's extension, a deep
# child's datasource, ...). It is *only* ever produced by a declared output -- a live
# dataset always has a concrete value -- so it is what turns a "no" into a "maybe".
UNKNOWN = object()

# The columns that make a CSV rankable; three of them must be present (see get_columns
# / is_rankable on DataSet). Rankability is worked out from the columns and extension a
# subject has, so it never needs declaring separately.
_RANK_COLUMNS = {"date", "value", "item"}


def _maybe_call(subject, method, **kwargs):
    """
    Read `subject.method` without assuming it exists: call it when it is a method,
    return it when it is a plain attribute, and return None when it is missing or
    raises. A DataSet exposes these as methods, so this keeps DatasetShape simple.
    """
    attr = getattr(subject, method, None)
    if attr is None:
        return None
    if callable(attr):
        try:
            return attr(**kwargs)
        except Exception:
            # a failing get_columns()/get_extension() reads as "no value", never a crash
            return None
    return attr


# TODO: memoize shutil.which() (used by is_executable / ExecutableSibling) -- its result
# is constant per process, so a cached wrapper (positive results only) would avoid
# repeated $PATH scans on video-heavy pages.
def is_executable(path):
    """
    Matcher for `required_settings`: the setting's value must point to an executable
    found on the system (resolved with `shutil.which`). An unset value fails safely::

        required_settings={("video-downloader.ffmpeg_path", is_executable)}
    """
    return bool(path) and shutil.which(path) is not None


class ExecutableSibling:
    """
    Matcher for `required_settings`: the configured executable must resolve AND a sibling
    executable must exist next to it, found by swapping the name in the resolved path.
    For tools that ship together, e.g. ffprobe alongside ffmpeg::

        required_settings={("video-downloader.ffmpeg_path",
                             ExecutableSibling("ffmpeg", "ffprobe"))}
    """

    def __init__(self, name, sibling):
        self.name = name
        self.sibling = sibling

    def __call__(self, path):
        resolved = shutil.which(path) if path else None
        if not resolved:
            return False
        # if `name` is not in the resolved path the swap below is a no-op and we would
        # re-check the same executable -- a false positive that never finds the sibling
        if self.name not in resolved:
            return False
        return shutil.which(self.sibling.join(resolved.rsplit(self.name, 1))) is not None


@dataclass
class Compatibility:
    """
    Declarative compatibility specification for a processor.

    Any axis left unset (None, or empty) is not checked. The four identity axes --
    types, type_prefixes, media_types and datasources -- describe what kind of input the
    processor accepts; if any are set, the subject must match at least one (they are
    OR-ed). Every other axis is an additional requirement that must also hold (AND-ed).
    """

    # --- Identity axes: what kind of input (match at least one of these) ---
    # Dataset types the processor accepts, matched exactly.
    types: Optional[Iterable[str]] = None
    # Dataset type prefixes the processor accepts, matched with str.startswith.
    type_prefixes: Optional[Iterable[str]] = None
    # Media types the processor accepts, e.g. {"video", "image", "audio", "text"}.
    media_types: Optional[Iterable[str]] = None
    # Datasources the processor accepts, e.g. {"4chan", "reddit"}.
    datasources: Optional[Iterable[str]] = None
    # Accepts a collector's output (a dataset whose type ends in -search or -import).
    is_collector: bool = False

    # --- Gates: extra conditions that must all hold ---
    # Dataset types this processor CANNOT run on -- a hard veto. Use when it would fail
    # or produce garbage on that type (e.g. download_videos on telegram-search). For a
    # soft "don't suggest" use excluded_followups on the producer instead.
    excluded_types: Iterable[str] = ()
    # Accepts only a top-level dataset (no parent) / only a non-top-level (child) one.
    top_dataset_only: bool = False
    child_only: bool = False
    # Result-file extensions the processor accepts, e.g. {"csv", "ndjson"}.
    extensions: Optional[Iterable[str]] = None

    # --- Column/rankability gates (read from the produced data) ---
    # When set, the subject's rankability must equal this. Worked out from its columns
    # and extension (a CSV with date/value/item), so it is never declared directly.
    rankable: Optional[bool] = None
    # Forwarded to the rank check: False rejects multi-value word_1/word_2/... rankings.
    rankable_multiple_items: bool = True
    # Columns that must ALL be present / of which AT LEAST ONE must be present.
    requires_all_columns: Iterable[str] = ()
    requires_any_columns: Iterable[str] = ()

    # --- Environment requirements (about the machine, not the dataset) ---
    # Executables that must be on the system path (checked with shutil.which).
    required_packages: Iterable[str] = ()
    # Configuration the processor needs. Each entry is a setting key (which must be
    # truthy) or a (key, expected) pair; `expected` may be a value the setting must
    # equal, a collection it must be in, or a function that validates it.
    required_settings: Iterable = ()

    # --- Follow-up hints (not a requirement -- they describe this processor's output) ---
    # Processor types to recommend first as next steps for this processor's output.
    preferred_followups: Iterable[str] = ()
    # Processor types never suggested after this one (a soft filter; they can still be
    # run directly). For "would fail on this output" use that processor's excluded_types.
    excluded_followups: Iterable[str] = ()

    # -- the one comparison --

    def check(self, subject) -> str:
        """
        Compare `subject` against this spec, returning "yes", "no" or "maybe".

        `subject` is a live dataset (DatasetShape) or a declared output (Shape); both
        answer the same questions, a real value or UNKNOWN when an output has not said.
        "no" means a condition is definitely unmet; "maybe" means everything known
        passes but the output left something we check undefined; "yes" means all met. A
        live dataset knows all its values, so for a dataset the answer is only yes/no.

        Only the data shape is compared here; the environment is environment_ok().
        """
        maybe = False

        # identity -- if we name any kind of input, the subject must be one of them
        if self._accepts_a_kind():
            kind = self._kind_result(subject)
            if kind == "no":
                return "no"
            if kind == "maybe":
                maybe = True

        # a type we refuse outright
        if subject.type in set(self.excluded_types):
            return "no"

        # structural position
        if self.top_dataset_only:
            if subject.top_level is UNKNOWN:
                maybe = True
            elif not subject.top_level:
                return "no"
        if self.child_only:
            if subject.top_level is UNKNOWN:
                maybe = True
            elif subject.top_level:
                return "no"

        # file extension
        if self.extensions:
            if subject.extension is UNKNOWN:
                maybe = True
            elif subject.extension not in set(self.extensions):
                return "no"

        # columns the processor needs to read
        if self.requires_all_columns or self.requires_any_columns:
            columns = self._columns_result(subject)
            if columns == "no":
                return "no"
            if columns == "maybe":
                maybe = True

        # rankable (a CSV with date/value/item columns)
        if self.rankable is not None:
            rankable = _is_rankable(subject, self.rankable_multiple_items)
            if rankable is UNKNOWN:
                maybe = True
            elif rankable != self.rankable:
                return "no"

        return "maybe" if maybe else "yes"

    def is_compatible_with(self, module, config=None) -> bool:
        """
        Whether a real dataset can be run on. A live dataset knows all its values, so
        check() is only ever "yes"/"no" here. `module` is normally a DataSet.
        """
        return self.check(DatasetShape(module)) == "yes" and self.environment_ok(config)

    def environment_ok(self, config=None) -> bool:
        """
        Whether the system has the settings and executables the processor needs. This is
        about the machine, not the dataset, so the map surfaces it as a note on the
        processor rather than removing a connection.
        """
        for requirement in self.required_settings:
            key, expected = (requirement, None) if isinstance(requirement, str) else requirement
            value = config.get(key) if config is not None else None
            if expected is None:
                met = bool(value)
            elif callable(expected):
                met = bool(expected(value))
            elif isinstance(expected, (set, frozenset, list, tuple)):
                met = value in expected
            else:
                met = value == expected
            if not met:
                return False
        for package in self.required_packages:
            if not shutil.which(package):
                return False
        return True

    @property
    def requires_dataset_result_file(self) -> bool:
        """
        Whether fully deciding this spec needs the produced data -- true when it gates on
        rankability or columns, both read from the result file. The map exposes this so
        the UI can say "you'll only know for certain once it runs".
        """
        return (self.rankable is not None
                or bool(self.requires_all_columns)
                or bool(self.requires_any_columns))

    # -- helpers for check(); each returns "yes"/"no"/"maybe" --

    def _accepts_a_kind(self) -> bool:
        """Whether the spec names any kind of input it accepts."""
        return self.is_collector or any(axis is not None for axis in
                                        (self.types, self.type_prefixes, self.media_types, self.datasources))

    def _kind_result(self, subject) -> str:
        """Identity is OR: "yes" if the subject is any kind we accept, "no" only if it is
        definitely none, else "maybe"."""
        maybe = False
        for outcome in self._kind_checks(subject):
            if outcome == "yes":
                return "yes"
            if outcome == "maybe":
                maybe = True
        return "maybe" if maybe else "no"

    def _kind_checks(self, subject):
        """One outcome per identity axis the spec declares, cheapest first."""
        if self.types is not None:
            yield "yes" if subject.type in set(self.types) else "no"
        if self.type_prefixes is not None:
            yield "yes" if (subject.type and subject.type.startswith(tuple(self.type_prefixes))) else "no"
        if self.media_types is not None:
            yield _media_result(set(self.media_types), subject.media)
        if self.datasources is not None:
            if subject.datasource is UNKNOWN:
                yield "maybe"
            else:
                yield "yes" if subject.datasource in set(self.datasources) else "no"
        if self.is_collector:
            if subject.from_collector is UNKNOWN:
                yield "maybe"
            else:
                yield "yes" if subject.from_collector else "no"

    def _columns_result(self, subject) -> str:
        """Does the subject have the columns we need? A missing column is a definite "no"
        only when we know its columns are the complete set (a real dataset, or an output
        that has none); an output floor might still gain the column, so it is "maybe"."""
        columns = subject.columns
        if columns is UNKNOWN:
            return "maybe"
        complete = subject.columns_are_all
        outcome = "yes"
        if self.requires_all_columns and not set(self.requires_all_columns) <= columns:
            if complete:
                return "no"
            outcome = "maybe"
        if self.requires_any_columns and not (columns & set(self.requires_any_columns)):
            if complete:
                return "no"
            outcome = "maybe"
        return outcome


def _media_result(accepted, media) -> str:
    """Compare a set of accepted media against a subject's media, which may be one value,
    a set of possible values (a media archive that could hold image OR video), or
    UNKNOWN."""
    if media is UNKNOWN:
        return "maybe"
    values = set(media) if isinstance(media, (set, frozenset)) else {media}
    if values <= accepted:
        return "yes"
    if values & accepted:
        return "maybe"
    return "no"


def _is_rankable(subject, multiple_items):
    """Whether the subject is rankable: a CSV with at least three of the ranking columns.
    UNKNOWN when the output has not pinned its extension or columns."""
    ranking = _RANK_COLUMNS | ({"word_1"} if multiple_items else set())
    extension, columns = subject.extension, subject.columns
    if extension is UNKNOWN:
        return UNKNOWN                    # can't tell whether it's a CSV
    if extension != "csv":
        return False                      # a known non-CSV is never rankable
    if columns is UNKNOWN:
        return UNKNOWN                     # a CSV, but its columns aren't declared
    if len(columns & ranking) >= 3:
        return True
    return False if subject.columns_are_all else UNKNOWN


class DatasetShape:
    """
    A live dataset, presented as the plain properties check() reads. Every value comes
    from the dataset's own methods, so it is always concrete -- a real dataset is never
    "maybe". Read lazily and cached, so the slower reads (columns) happen only for a spec
    that actually needs them.
    """

    columns_are_all = True  # a real dataset's columns are all the columns it has

    def __init__(self, dataset):
        self._dataset = dataset

    @property
    def type(self):
        return getattr(self._dataset, "type", None)

    @cached_property
    def extension(self):
        return _maybe_call(self._dataset, "get_extension")

    @cached_property
    def media(self):
        return _maybe_call(self._dataset, "get_media_type") or getattr(self._dataset, "media_type", None)

    @cached_property
    def datasource(self):
        parameters = getattr(self._dataset, "parameters", None) or {}
        return parameters.get("datasource") if isinstance(parameters, dict) else None

    @cached_property
    def top_level(self):
        return bool(_maybe_call(self._dataset, "is_top_dataset"))

    @cached_property
    def from_collector(self):
        return bool(_maybe_call(self._dataset, "is_from_collector"))

    @cached_property
    def columns(self):
        columns = _maybe_call(self._dataset, "get_columns")
        return frozenset(columns) if columns else frozenset()


@dataclass(frozen=True)
class Shape:
    """
    A processor's declared output, as the plain properties check() reads. A value is
    UNKNOWN when the processor's Output leaves it open (a filter's extension, say).
    `columns_are_all` is True only when the output has NO columns; a declared column set
    is a floor (at least these), so it is False. Built from an Output in outputs.py, or
    inferred from the class for a processor that declares none.
    """

    type: Optional[str]
    extension: object = UNKNOWN       # a str, or UNKNOWN
    media: object = UNKNOWN            # a str, a set of str, or UNKNOWN
    datasource: object = UNKNOWN       # a str, or UNKNOWN
    top_level: object = UNKNOWN        # a bool, or UNKNOWN
    from_collector: object = UNKNOWN   # a bool, or UNKNOWN
    columns: object = UNKNOWN          # a frozenset, or UNKNOWN
    columns_are_all: bool = False
    produces_file: bool = True


# ---------------------------------------------------------------------------
# Helpers shared with outputs.py (which builds a Shape and needs to know a processor's
# collector-ness), and the spec serialiser the catalogue displays.
# ---------------------------------------------------------------------------

def _is_collector_type(type_id) -> bool:
    """A collector/datasource output: its type ends in `-search` or `-import`."""
    return bool(type_id) and (type_id.endswith("-search") or type_id.endswith("-import"))


def _declared_class_value(processor, name):
    """
    The value of class attribute `name` if the processor (or a parent class below
    BasicProcessor) actually sets it, otherwise None. This tells a real choice apart from
    a value merely inherited from BasicProcessor (the `extension = "csv"` default every
    processor gets for free). A shared parent such as Search or a base filter counts as a
    real choice; BasicProcessor itself, and anything above it, does not.
    """
    cls = processor if isinstance(processor, type) else type(processor)
    try:
        from backend.lib.processor import BasicProcessor
    except Exception:
        BasicProcessor = None
    for klass in cls.__mro__:
        if klass is object or klass is BasicProcessor or klass.__name__ == "BasicProcessor":
            break
        if name in vars(klass):
            return vars(klass)[name]
    return None


def is_collector(processor) -> bool:
    """
    Whether a processor starts a chain -- a Search subclass, or (fallback) a
    -search/-import type. This is about its role as a starting point, separate from
    whether its *output* counts as a collector's (a filter's result can be made to look
    like one, so that is left unknown for a filter).
    """
    try:
        from backend.lib.search import Search
        if isinstance(processor, type) and issubclass(processor, Search):
            return True
    except Exception:
        pass
    return _is_collector_type(getattr(processor, "type", None))


def is_declaratively_compatible(processor) -> bool:
    """
    Whether the processor relies solely on its declared `compatibility` -- i.e. it does
    NOT keep a custom `is_compatible_with`. When False it escapes into runtime logic the
    specs can't see, so a map built from specs alone can only approximate edges into it.
    """
    try:
        from backend.lib.processor import BasicProcessor
    except Exception:
        return True
    own = getattr(getattr(processor, "is_compatible_with", None), "__func__", None)
    base = getattr(BasicProcessor.is_compatible_with, "__func__", None)
    has_override = own is not None and base is not None and own is not base
    return not has_override


def describe_spec(spec) -> Optional[dict]:
    """
    Serialise a Compatibility to a dict of only its *declared* axes, for display and as
    the "requirement" label in the map. Defaults and empties are omitted, so what shows
    is exactly what the processor opted into. Returns None for an undeclared spec.

    (test_describe_spec_covers_every_compatibility_axis asserts every axis appears here.)
    """
    if spec is None:
        return None

    def norm(value):
        if isinstance(value, (set, frozenset)):
            return sorted(value)
        if isinstance(value, (list, tuple)):
            return list(value)
        return value

    declared = {}
    for axis in ("types", "type_prefixes", "media_types", "datasources"):
        value = getattr(spec, axis, None)
        if value:
            declared[axis] = norm(value)
    if getattr(spec, "is_collector", False):
        declared["is_collector"] = True
    if getattr(spec, "extensions", None):
        declared["extensions"] = norm(spec.extensions)
    for gate in ("top_dataset_only", "child_only"):
        if getattr(spec, gate, False):
            declared[gate] = True
    if getattr(spec, "excluded_types", None):
        declared["excluded_types"] = norm(spec.excluded_types)
    if getattr(spec, "rankable", None) is not None:
        declared["rankable"] = spec.rankable
    if getattr(spec, "requires_all_columns", None):
        declared["requires_all_columns"] = norm(spec.requires_all_columns)
    if getattr(spec, "requires_any_columns", None):
        declared["requires_any_columns"] = norm(spec.requires_any_columns)
    if getattr(spec, "required_settings", None):
        keys = [r if isinstance(r, str) else r[0] for r in spec.required_settings]
        declared["required_settings"] = sorted(keys)
    if getattr(spec, "required_packages", None):
        declared["required_packages"] = norm(spec.required_packages)
    for followup in ("preferred_followups", "excluded_followups"):
        value = getattr(spec, followup, None)
        if value:
            declared[followup] = norm(value)
    return declared
