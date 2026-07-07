"""
What a processor produces.

A processor states the shape of its output as an `output` class attribute -- an Output,
usually one of the archetypes below. This is the counterpart to Compatibility (what a
processor accepts): the two together let the processor map decide which processors can
follow which, without running anything.

Most processors never write one by hand -- the base classes set a sensible default (a
data source produces an ndjson table, a filter passes its parent's shape through) and a
processor overrides only the field that differs, e.g. `output = Table(columns={"date",
"item", "value"})`. The archetypes:

    Datasource    a collected, top-level table (its own extension, columns from its items)
    Table         a derived table (csv/ndjson)
    Filter        same shape as the parent (extension, media and columns pass through)
    Network       a single graph file (gexf), no columns
    Render        a single image (svg/png), no columns
    MediaArchive  a zip of media files, no columns
    Archive       a zip of data files, no columns
    File          a single json/txt/html file, no columns
    Delegated     a preset whose real output is its pipeline's last step (unknown here)
    NoOutput      writes no result file (e.g. only adds annotations to its parent)

`describe_output(processor)` turns the declaration into a Shape -- the plain properties
Compatibility.check reads -- filling in UNKNOWN for anything left open. A processor that
declares nothing falls back to inferring a Shape from its class.
"""
from __future__ import annotations

from common.lib.compatibility import (
    Shape,
    UNKNOWN,
    _is_collector_type,
    is_collector,
    _maybe_call,
    _declared_class_value,
)


class _Sentinel:
    def __init__(self, name):
        self._name = name

    def __repr__(self):
        return self._name


# Use for any field whose value is the parent dataset's (a filter's extension, media or
# columns) -- unknown until the chain is known, so it only ever softens an answer.
PASSTHROUGH = _Sentinel("PASSTHROUGH")
# Use as an extension when the processor's own `extension` class attribute is the real,
# trusted value (a data source whose subclasses each set their own).
CLASS_EXTENSION = _Sentinel("CLASS_EXTENSION")
# Use as `columns` when the output has no column table at all (a network, image, or media
# archive). A consumer that needs a column then gets a definite "no".
NO_COLUMNS = _Sentinel("NO_COLUMNS")


def _extension_value(value, processor):
    if value is PASSTHROUGH or value is None:
        return UNKNOWN
    if value is CLASS_EXTENSION:
        return getattr(processor, "extension", None) or UNKNOWN
    return value  # a plain extension string


def _media_value(value):
    if value is None or value is PASSTHROUGH:
        return UNKNOWN
    if isinstance(value, (set, frozenset, list, tuple)):
        return set(value)  # a bounded set: could be image OR video OR ...
    return value  # a single media string


def _datasource_value(value, collector, ptype):
    if value is not None and value is not PASSTHROUGH:
        return value
    # a collector carries its datasource in its type; anything else passes it through
    if collector and _is_collector_type(ptype):
        return ptype.rsplit("-", 1)[0]
    return UNKNOWN


def _top_level_value(position):
    if position == "top":
        return True
    if position == "child":
        return False
    return UNKNOWN


def _columns_value(value):
    """Returns (columns, columns_are_all) the way Shape wants them."""
    if value is None or value is PASSTHROUGH:
        return UNKNOWN, False
    if value is NO_COLUMNS:
        return frozenset(), True  # definitely no columns
    return frozenset(value), False  # a floor: at least these


class Output:
    """
    The shape a processor produces. Subclass it for the common archetypes; the fields are
    kept as plain values and turned into a Shape by to_shape. Any field left None is
    "unknown" -- it can never cause a false "no", only soften an answer to "maybe".
    `produces_file` is False for a processor that writes no result file.
    """

    def __init__(self, *, extension=None, media="text", columns=None,
                 position="child", collector=False, datasource=None, produces_file=True):
        self.extension = extension      # str | set | PASSTHROUGH | CLASS_EXTENSION | None
        self.media = media              # str | set | PASSTHROUGH | None
        self.columns = columns          # set | NO_COLUMNS | PASSTHROUGH | None
        self.position = position        # "top" | "child" | None
        self.collector = collector      # bool | None
        self.datasource = datasource    # str | PASSTHROUGH | None
        self.produces_file = produces_file

    def to_shape(self, processor) -> Shape:
        """Turn this into the Shape Compatibility.check reads. `processor` supplies the
        type (and, for a collector, the datasource it carries)."""
        ptype = getattr(processor, "type", None)
        columns, columns_are_all = _columns_value(self.columns)
        return Shape(
            type=ptype,
            extension=_extension_value(self.extension, processor),
            media=_media_value(self.media),
            datasource=_datasource_value(self.datasource, self.collector, ptype),
            top_level=_top_level_value(self.position),
            from_collector=UNKNOWN if self.collector is None else bool(self.collector),
            columns=columns,
            columns_are_all=columns_are_all,
            produces_file=self.produces_file,
        )


# Default archetypes for the common processor types. A processor can override any field
# by declaring its own Output (or subclass) as its `output` class attribute.

class Datasource(Output):
    """A collected, top-level dataset. Its extension is its own (ndjson for most, csv or
    zip for some), trusted because it drives the result file. Defaults to text items;
    pass `columns` to sharpen. A data source producing media uses MediaArchive."""

    def __init__(self, *, extension=CLASS_EXTENSION, columns=None, media="text", datasource=None):
        super().__init__(extension=extension, media=media, columns=columns,
                         position="top", collector=True, datasource=datasource)


class Table(Output):
    """A derived table. Defaults to a csv of text; pass `columns` to sharpen."""

    def __init__(self, *, columns=None, media="text", extension="csv"):
        super().__init__(extension=extension, media=media, columns=columns,
                         position="child", collector=False)


class Filter(Output):
    """A filter: extension, media and columns all follow the parent, and its position and
    collector-ness are unknown (its result may be made standalone)."""

    def __init__(self):
        super().__init__(extension=PASSTHROUGH, media=PASSTHROUGH, columns=PASSTHROUGH,
                         position=None, collector=None, datasource=PASSTHROUGH)


class Network(Output):
    """A single graph file (gexf) with no column table."""

    def __init__(self, *, extension="gexf"):
        super().__init__(extension=extension, media="text", columns=NO_COLUMNS,
                         position="child", collector=False)


class Render(Output):
    """A single rendered image (svg by default, or png) with no column table."""

    def __init__(self, extension="svg", *, media="image"):
        super().__init__(extension=extension, media=media, columns=NO_COLUMNS,
                         position="child", collector=False)


class MediaArchive(Output):
    """A zip archive of media files with no column table. `media` is the kind of media in
    it (a single value, or a set when it varies per file)."""

    def __init__(self, *, media=None, collector=False, position="child"):
        if media is None:
            media = {"image", "video", "audio", "file"}
        super().__init__(extension="zip", media=media, columns=NO_COLUMNS,
                         position=position, collector=collector)


class Archive(Output):
    """A zip archive of data files with no column table (tokens, embeddings, an export
    bundle). For an archive of media files use MediaArchive."""

    def __init__(self, *, media="text", collector=False, position="child"):
        super().__init__(extension="zip", media=media, columns=NO_COLUMNS,
                         position=position, collector=collector)


class File(Output):
    """A single non-tabular file (e.g. json, txt, html) with no column table."""

    def __init__(self, extension, *, media="text"):
        super().__init__(extension=extension, media=media, columns=NO_COLUMNS,
                         position="child", collector=False)


class Delegated(Output):
    """A preset that writes no file of its own; its real output is whatever the last
    processor in its pipeline produces, so the shape is unknown here. `terminal` names
    that last processor when it is known."""

    def __init__(self, terminal=None):
        super().__init__(extension=PASSTHROUGH, media=None, columns=None,
                         position=None, collector=False)
        self.terminal = terminal


class NoOutput(Output):
    """Produces no result file (for example, only adds annotations to its parent), so
    nothing can run on it."""

    def __init__(self):
        super().__init__(extension=None, media=None, columns=NO_COLUMNS,
                         position=None, collector=False, produces_file=False)


def _infer_output(processor) -> Shape:
    """
    Work out a processor's output from its class -- the fallback for a processor that
    declares no `output` (today only third-party extensions). It synthesises a plain
    Output from what the class safely promises and hands it to to_shape, so the
    class-to-shape conversion lives in one place. A filter is passthrough; a collector is
    top-level with its datasource; anything else is a child with its trusted class
    extension (an inherited default stays unknown, never a false claim).
    """
    collector = is_collector(processor)
    is_filter = bool(_maybe_call(processor, "is_filter"))
    declared_media = _declared_class_value(processor, "media_type")

    if collector:
        position, collector_flag = "top", True
    elif is_filter:
        position, collector_flag = None, None
    else:
        position, collector_flag = "child", False

    extension = PASSTHROUGH if is_filter else _declared_class_value(processor, "extension")

    return Output(
        extension=extension,
        media=declared_media or None,
        columns=None,
        position=position,
        collector=collector_flag,
    ).to_shape(processor)


def describe_output(processor) -> Shape:
    """
    A processor's output as a Shape Compatibility.check can read. Reads the processor's
    declared `output` when it has one; otherwise falls back to inferring it from the
    class. The single place that chooses between the two, so everything downstream reads
    one kind of shape regardless.
    """
    declared = getattr(processor, "output", None)
    if isinstance(declared, Output):
        return declared.to_shape(processor)
    return _infer_output(processor)
