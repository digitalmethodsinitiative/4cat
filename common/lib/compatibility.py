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


def _maybe_call(module, method):
    """
    Read `module.method` without assuming it exists.

    Calls it and returns the result when it is a method, returns the value when
    it is a plain attribute, and returns None when it is missing or raises. A
    DataSet exposes these as methods; a processor class exposes some of them as
    well, and this keeps the same check working for both.
    """
    attr = getattr(module, method, None)
    if attr is None:
        return None
    if callable(attr):
        try:
            return attr()
        except Exception:
            return None
    return attr


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

    # --- consumed data shape: identity (the module must match one of these) ---
    # Dataset types the processor accepts, matched exactly.
    types: Optional[Iterable[str]] = None
    # Dataset type prefixes the processor accepts, matched with str.startswith.
    type_prefixes: Optional[Iterable[str]] = None
    # Media types the processor accepts, e.g. {"video", "image", "audio", "text"}.
    media_types: Optional[Iterable[str]] = None
    # Datasources the processor accepts, e.g. {"4chan", "reddit"}.
    datasources: Optional[Iterable[str]] = None

    # --- structural gates (each must hold when set) ---
    # Result-file extensions the processor accepts, e.g. {"csv", "ndjson"}.
    extensions: Optional[Iterable[str]] = None
    # When True, the processor only accepts a top-level dataset (one with no parent).
    top_dataset_only: bool = False
    # When set, the dataset's is_rankable() must equal this. None means it does not matter.
    rankable: Optional[bool] = None
    # Columns that must all be present in the dataset. This can only be checked
    # against a real dataset, as it reads the dataset's columns.
    requires_columns: Iterable[str] = ()

    # --- environment requirements ---
    # Executables that must be found on the system path (checked with shutil.which).
    required_packages: Iterable[str] = ()
    # Configuration the processor needs. Each entry is either a setting key,
    # which must resolve to a truthy value, or a (key, expected) pair. The
    # expected part may be a single value the setting must equal, a collection
    # the setting's value must be in, or a function that receives the value and
    # returns whether it is acceptable.
    required_settings: Iterable = ()

    # --- follow-up processors ---
    # Processor types to recommend first as next steps for this processor's output.
    preferred_followups: Iterable[str] = ()
    # Processor types that should never be offered as follow-ups here, even
    # when they are otherwise compatible.
    excluded_followups: Iterable[str] = ()

    def is_compatible_with(self, module, config=None) -> bool:
        """
        Return whether `module` meets every requirement in this specification.

        `module` is normally a DataSet but may be a processor class. `config`
        is the configuration reader, or None when none is available.
        """
        return not self.unmet_requirements(module, config=config)

    def unmet_requirements(self, module, config=None) -> List[str]:
        """
        Return the requirements `module` does not meet, as readable strings.

        An empty list means `module` is compatible. Each string names one thing
        that is missing -- a wrong dataset type, an absent column, a setting
        that is not configured, and so on.
        """
        reasons: List[str] = []
        if module is None:
            return ["no dataset provided"]

        # if the processor names the kinds of dataset it accepts, the module
        # must be one of them
        if self._identity_declared() and not self._identity_matches(module):
            reasons.append("dataset type/media is not accepted")

        if self.top_dataset_only and not _maybe_call(module, "is_top_dataset"):
            reasons.append("requires a top-level dataset")

        if self.extensions is not None:
            extension = _maybe_call(module, "get_extension")
            if extension not in set(self.extensions):
                reasons.append("requires extension: %s" % ", ".join(self.extensions))

        if self.rankable is not None:
            if bool(_maybe_call(module, "is_rankable")) != self.rankable:
                reasons.append(
                    "requires a rankable dataset" if self.rankable
                    else "requires a non-rankable dataset"
                )

        # the only check that really needs a DataSet object
        if self.requires_columns:
            columns = _maybe_call(module, "get_columns") or []
            missing = [column for column in self.requires_columns if column not in columns]
            if missing:
                reasons.append("requires column(s): %s" % ", ".join(missing))

        for requirement in self.required_settings:
            key, expected = (requirement, None) if isinstance(requirement, str) else requirement
            value = config.get(key) if config is not None else None
            # no expected value; just check that the setting is truthy
            if expected is None:
                met = bool(value)
            # some function to check (special check for things like {"video-downloader.ffmpeg_path": lambda p: shutil.which(p) is not None})
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

        for package in self.required_packages:
            if not shutil.which(package):
                reasons.append("requires package: %s" % package)

        return reasons

    def _identity_declared(self) -> bool:
        """Whether the processor names any kind of dataset it accepts."""
        return any(
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

        return False
