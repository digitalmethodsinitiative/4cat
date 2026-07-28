"""
Declarative processor compatibility.

A Compatibility object describes the conditions under which a processor can run
on a dataset:

* the data shape it consumes -- the dataset's type, file extension, media type,
  datasource, and any columns it needs;
* the environment it needs -- external executables and 4CAT configuration
  settings;
* the follow-up processors that are most relevant for its output, and any that
  should never be offered.

A processor declares one as its `compatibility` class attribute, for example::

    compatibility = Compatibility(
        media_types={"video"},
        type_prefixes={"video-downloader"},
        required_settings={("video-downloader.ffmpeg_path", is_executable)},
    )

BasicProcessor.is_compatible_with() evaluates it. A processor whose
requirements cannot be expressed this way -- for example one that must inspect
a dataset's ancestry -- may override is_compatible_with() instead; the override
is used in preference to the attribute.

`_maybe_call`: a utility function to safely read attributes or call methods on a
 module, handling cases where the attribute or method might not exist or raise an exception.
Normally a `module` is a DataSet, but the values read here (its type, extension, media type
and so on) are also available on a processor class, so a processor can be checked even when 
no dataset exists yet.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from typing import Iterable, List, Optional


def _maybe_call(module, method, **kwargs):
    """
    Read `module.method` without assuming it exists.

    Calls it and returns the result when it is a method, returns the value when
    it is a plain attribute, and returns None when it is missing or raises. A
    DataSet exposes these as methods; a processor class exposes some of them as
    well, and this keeps the same check working for both. Any keyword arguments
    are forwarded to the call (e.g. is_rankable(multiple_items=False)).
    """
    attr = getattr(module, method, None)
    if attr is None:
        return None
    if callable(attr):
        try:
            return attr(**kwargs)
        except Exception:
            # deliberately swallowed: a failing get_columns()/is_rankable() reads
            # as "cannot determine"; could pass logger here to debug in case there is
            # a real bug, but this caller is expected to handle None as "not met"
            return None
    return attr


# TODO: memoize shutil.which() (used by is_executable / ExecutableSibling) -- its
# result is constant per process, so a cached wrapper (positive results only, to
# avoid stale negatives if an executable is installed without a restart) would
# avoid repeated $PATH scans on video-heavy pages.
def is_executable(path):
    """
    Matcher for `required_settings`: the setting's value must point to an
    executable found on the system (resolved with `shutil.which`). An unset or
    empty value fails safely, e.g.::

        required_settings={("video-downloader.ffmpeg_path", is_executable)}
    """
    return bool(path) and shutil.which(path) is not None


class ExecutableSibling:
    """
    Matcher for `required_settings`: the configured executable must resolve (via
    `shutil.which`) AND a sibling executable must exist next to it, found by
    swapping the name in the resolved path. For tools that ship together, e.g.
    ffprobe alongside ffmpeg::

        required_settings={("video-downloader.ffmpeg_path",
                             ExecutableSibling("ffmpeg", "ffprobe"))}

    The matcher protocol is a one-argument callable, so arguments are passed via
    the constructor; `name`/`sibling` stay readable for a future UI. None-safe.
    """

    def __init__(self, name, sibling):
        self.name = name
        self.sibling = sibling

    def __call__(self, path):
        resolved = shutil.which(path) if path else None
        if not resolved:
            return False
        # if `name` is not in the resolved path, the rsplit/join below leaves it
        # unchanged and we would re-check the same executable -- a false positive
        # that never actually locates the sibling. Fail instead.
        if self.name not in resolved:
            return False
        return shutil.which(self.sibling.join(resolved.rsplit(self.name, 1))) is not None


@dataclass
class Compatibility:
    """
    Declarative compatibility specification for a processor.

    Any axis left unset (None, or empty) is not checked.

    The four identity axes -- types, type_prefixes, media_types and
    datasources -- describe what kind of dataset the processor accepts. If any
    of them are set, the module must match at least one (they are OR-ed).
    Every other axis is an additional requirement that must also hold (they are
    AND-ed).
    """

    # --- Identity axes: consumed data shape (the module must match one of these) ---
    # Dataset types the processor accepts, matched exactly.
    types: Optional[Iterable[str]] = None
    # Dataset type prefixes the processor accepts, matched with str.startswith.
    type_prefixes: Optional[Iterable[str]] = None
    # Media types the processor accepts, e.g. {"video", "image", "audio", "text"}.
    media_types: Optional[Iterable[str]] = None
    # Datasources the processor accepts, e.g. {"4chan", "reddit"}.
    datasources: Optional[Iterable[str]] = None
    # Collectors types (a dataset whose type ends in -search or -import) 
    # Compare with top_dataset_only, which reads key_parent; the two cover nearly 
    # the same datasets but differ in role (identity/OR vs gate/AND)
    is_collector: bool = False

    # --- Shape gates (structural checks) ---
     # Parent dataset types this processor CANNOT run on -- a hard gate
    # (is_compatible_with returns False). Use when the processor would fail or
    # produce garbage on that type (e.g. download_videos on telegram-search).
    # For a soft filter use excluded_followups on the producer instead.
    excluded_types: Iterable[str] = ()

    # --- DataSet required gates ---
    # The ground truth requires an existing DataSet to read its produced data
    # TODO: processors could declare these attributes more explicitly
    # When True, the processor only accepts a top-level dataset (one with no parent).
    top_dataset_only: bool = False
    # When True, the processor only accepts a non-top-level (child) dataset -- the
    # inverse of top_dataset_only.
    child_only: bool = False
    # Result-file extensions the processor accepts, e.g. {"csv", "ndjson"}.
    extensions: Optional[Iterable[str]] = None

    # --- Result file gates (reading the actual file is required)
    # TODO: processors again could point to these attributes more explicitly if known
    # dataset and cannot be resolved from a processor class -- see requires_dataset) ---
    # When set, is_rankable() must equal this (read from the result file). None = not checked.
    rankable: Optional[bool] = None
    # Forwarded to is_rankable(multiple_items=...) when `rankable` is set. False
    # restricts to single-value rankings (rejecting multi-column word_1/word_2/... rankings).
    rankable_multiple_items: bool = True
    # Columns that must ALL be present in the dataset, read from its columns.
    requires_all_columns: Iterable[str] = ()
    # Columns of which AT LEAST ONE must be present, read from its columns.
    requires_any_columns: Iterable[str] = ()

    # --- Environment requirements ---
    # Executables that must be found on the system path (checked with shutil.which).
    required_packages: Iterable[str] = ()
    # Configuration the processor needs. Each entry is either a setting key,
    # which must resolve to a truthy value, or a (key, expected) pair. The
    # expected part may be a single value the setting must equal, a collection
    # the setting's value must be in, or a function that receives the value and
    # returns whether it is acceptable.
    required_settings: Iterable = ()

    # --- Follow-up processors ---
    # Processor types to recommend first as next steps for this processor's output.
    preferred_followups: Iterable[str] = ()
    # Processor types never SUGGESTED as follow-ups after this one -- a soft
    # filter (affects the suggestion list only; is_compatible_with is unchanged,
    # so they can still be run directly). Use for "a more specific processor is
    # preferred here" (e.g. tiktok-search excludes the generic video-downloader).
    # For "that processor would fail on this output", use its excluded_types (hard).
    excluded_followups: Iterable[str] = ()

    @property
    def requires_dataset_result_file(self) -> bool:
        """
        Whether fully evaluating this spec needs the dataset's produced data.

        True when `rankable`, `requires_all_columns`, or `requires_any_columns` is
        set: all are read from the produced result file, so they cannot be
        resolved from a processor class alone. (Shape axes such as
        top_dataset/extension also read instance state, but they are recoverable
        from a dataset's shape; only these need the produced data, so only they
        are counted here.) A consumer that reasons about processors without real
        datasets (e.g. a processor map) can use this to mark those axes as
        undecided rather than treating them as failed.
        """
        return (self.rankable is not None
                or bool(self.requires_all_columns)
                or bool(self.requires_any_columns))

    def is_compatible_with(self, module, config=None) -> bool:
        """
        Return whether `module` meets every requirement in this specification.

        `module` is normally a DataSet but may be a processor class. `config`
        is the configuration reader, or None when none is available.
        """
        return not self.unmet_requirements(module, config=config)

    def unmet_requirements(self, module, config=None, first_only=True) -> List[str]:
        """
        Return the requirements `module` does not meet, as readable strings.

        An empty list means `module` is compatible. Each string names one thing
        that is missing -- a wrong dataset type, an absent column, a setting
        that is not configured, and so on.

        The checks run in three tiers, cheapest first so the short-circuit can
        skip later work once something fails:

        1. structural -- the dataset's shape (type, extension, parent,
           datasource); cheap, no result-file read. (Several still read instance
           state -- is_top_dataset() -> key_parent, get_extension(), parameters --
           so on a bare processor class they return a stub, not a real answer.)
        2. dataset-required -- `rankable`, `requires_all_columns`, and
           `requires_any_columns`, read from the produced result file, so they
           need a materialized DataSet (see `requires_dataset_result_file`);
        3. environment -- configuration settings and system executables.

        By default the method returns as soon as one requirement is unmet --
        enough for the yes/no `is_compatible_with`. Pass `first_only=False` to
        collect every unmet requirement -- used to explain why a module is not
        compatible.
        """
        reasons: List[str] = []
        if module is None:
            return ["no dataset provided"]

        # --- tier 1: structural shape (cheap; no result-file read) ---

        # if the processor names the kinds of dataset it accepts, the module
        # must be one of them
        if self._identity_declared() and not self._identity_matches(module):
            reasons.append("dataset type/media is not accepted")
            if first_only:
                return reasons

        if self.excluded_types and getattr(module, "type", None) in set(self.excluded_types):
            reasons.append("does not run on dataset type: %s" % getattr(module, "type", None))
            if first_only:
                return reasons

        if self.top_dataset_only and not _maybe_call(module, "is_top_dataset"):
            reasons.append("requires a top-level dataset")
            if first_only:
                return reasons

        if self.child_only and _maybe_call(module, "is_top_dataset"):
            reasons.append("requires a child (non-top-level) dataset")
            if first_only:
                return reasons

        if self.extensions is not None:
            extension = _maybe_call(module, "get_extension")
            if extension not in set(self.extensions):
                reasons.append("requires extension: %s" % ", ".join(self.extensions))
                if first_only:
                    return reasons

        # --- tier 2: dataset-required (read from the result file; cannot be
        # resolved from a processor class -- see requires_dataset_result_file) ---

        if self.rankable is not None:
            if bool(_maybe_call(module, "is_rankable", multiple_items=self.rankable_multiple_items)) != self.rankable:
                reasons.append(
                    "requires a rankable dataset" if self.rankable
                    else "requires a non-rankable dataset"
                )
                if first_only:
                    return reasons

        if self.requires_all_columns or self.requires_any_columns:
            columns = _maybe_call(module, "get_columns") or []
            missing = [column for column in self.requires_all_columns if column not in columns]
            if missing:
                reasons.append("requires all column(s): %s" % ", ".join(missing))
                if first_only:
                    return reasons
            if self.requires_any_columns and not any(column in columns for column in self.requires_any_columns):
                reasons.append("requires any of column(s): %s" % ", ".join(self.requires_any_columns))
                if first_only:
                    return reasons

        # --- tier 3: environment (needs config/system, not a DataSet; the
        # executable matchers here can be expensive, so this tier runs last.
        # TODO: cheap setting reads could be split out ahead of those matchers) ---
        for requirement in self.required_settings:
            key, expected = (requirement, None) if isinstance(requirement, str) else requirement
            value = config.get(key) if config is not None else None
            # no expected value; just check that the setting is truthy
            if expected is None:
                met = bool(value)
            # a function that validates the value (e.g. is_executable / ExecutableSibling)
            elif callable(expected):
                met = bool(expected(value))
            # a collection of acceptable values
            elif isinstance(expected, (set, frozenset, list, tuple)):
                met = value in expected
            # a single expected value
            else:
                met = value == expected
            if not met:
                reasons.append("requires setting: %s" % key)
                if first_only:
                    return reasons

        for package in self.required_packages:
            if not shutil.which(package):
                reasons.append("requires package: %s" % package)
                if first_only:
                    return reasons

        return reasons

    def _identity_declared(self) -> bool:
        """Whether the processor names any kind of dataset it accepts."""
        return self.is_collector or any(
            axis is not None
            for axis in (self.types, self.type_prefixes, self.media_types, self.datasources)
        )

    def _identity_matches(self, module) -> bool:
        """Whether the module is one of the kinds of dataset the processor accepts."""
        module_type = getattr(module, "type", None)

        if self.types is not None and module_type in set(self.types):
            return True

        if self.type_prefixes is not None and module_type is not None \
                and any(module_type.startswith(prefix) for prefix in self.type_prefixes):
            return True

        if self.media_types is not None:
            media = _maybe_call(module, "get_media_type") or getattr(module, "media_type", None)
            if media in set(self.media_types):
                return True

        if self.datasources is not None:
            parameters = getattr(module, "parameters", None) or {}
            if isinstance(parameters, dict) and parameters.get("datasource") in set(self.datasources):
                return True

        if self.is_collector and _maybe_call(module, "is_from_collector"):
            return True

        return False
