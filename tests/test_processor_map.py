"""
Tests for the compatibility check, the output-description helper, and the processor-map
query layer.

Two halves:

* plain unit tests on `Compatibility.check` -- comparing a spec against a subject
  (a live dataset or a declared output), and the rule that an output leaving a value
  UNKNOWN can only soften an answer to "maybe", never produce a false "no". No app
  context needed.
* tests against the real loaded modules (the `fourcat_modules` fixture from
  test_modules.py): every processor declares an output, declarations agree with the
  class attributes, and the map builds and answers questions.
"""
import pytest

from common.lib.compatibility import Compatibility, UNKNOWN, Shape, DatasetShape


# --- helpers ---------------------------------------------------------------

def shape(type=None, extension=UNKNOWN, media=UNKNOWN, datasource=UNKNOWN,
          top_level=False, from_collector=False, columns=UNKNOWN, columns_are_all=False):
    """A declared output; anything left as UNKNOWN reads as 'the output didn't say'."""
    return Shape(type=type, extension=extension, media=media, datasource=datasource,
                 top_level=top_level, from_collector=from_collector,
                 columns=columns, columns_are_all=columns_are_all)


class FakeModule:
    """A minimal live dataset exposing what DatasetShape reads."""

    def __init__(self, type=None, extension=None, media_type=None, datasource=None,
                 top=True, from_collector=False):
        self.type = type
        self._extension = extension
        self._media_type = media_type
        self.parameters = {"datasource": datasource} if datasource else {}
        self._top = top
        self._from_collector = from_collector

    def get_extension(self):
        return self._extension

    def get_media_type(self):
        return self._media_type

    def is_top_dataset(self):
        return self._top

    def is_from_collector(self):
        return self._from_collector


# --- check() against a declared output -------------------------------------

def test_check_definite_yes_and_no_on_known_media():
    assert Compatibility(media_types={"audio"}).check(shape(media="audio")) == "yes"
    assert Compatibility(media_types={"image"}).check(shape(media="audio")) == "no"


def test_unknown_value_is_maybe_never_false_no():
    # import_media sets its media only when it runs, so its output leaves media UNKNOWN;
    # a processor wanting images then gets "maybe", never a false "no"
    spec = Compatibility(media_types={"image"})
    assert spec.check(shape(media=UNKNOWN, from_collector=True, top_level=True)) == "maybe"


def test_unknown_extension_is_maybe_but_wrong_extension_is_no():
    spec = Compatibility(extensions={"ndjson"})
    assert spec.check(shape(extension=UNKNOWN)) == "maybe"   # the output didn't say
    assert spec.check(shape(extension="csv")) == "no"        # definitely the wrong one
    assert spec.check(shape(extension="ndjson")) == "yes"


def test_column_requirement_softens_to_maybe():
    spec = Compatibility(media_types={"audio"}, requires_all_columns={"author"})
    # media matches, but the output hasn't declared its columns -> maybe
    assert spec.check(shape(media="audio")) == "maybe"


def test_filter_position_is_maybe():
    # a filter's result may or may not be top-level -> top_level UNKNOWN -> maybe
    assert Compatibility(top_dataset_only=True).check(shape(top_level=UNKNOWN)) == "maybe"


def test_columns_requirement_resolved_against_declared_columns():
    spec = Compatibility(requires_all_columns={"author", "body"})
    # the output guarantees both -> yes
    assert spec.check(shape(columns=frozenset({"author", "body", "id"}))) == "yes"
    # a column not in the floor might still appear at run time -> maybe, never a false no
    assert spec.check(shape(columns=frozenset({"author"}))) == "maybe"
    # an output with no columns at all (columns_are_all) can never satisfy it -> no
    assert spec.check(shape(columns=frozenset(), columns_are_all=True)) == "no"
    # nothing declared -> maybe
    assert spec.check(shape(columns=UNKNOWN)) == "maybe"


def test_columns_any_requirement():
    spec = Compatibility(requires_any_columns={"image", "video"})
    assert spec.check(shape(columns=frozenset({"video"}))) == "yes"
    assert spec.check(shape(columns=frozenset(), columns_are_all=True)) == "no"


def test_rankable_derived_from_columns_and_extension():
    spec = Compatibility(rankable=True)
    # a csv guaranteeing the ranking columns is rankable
    assert spec.check(shape(extension="csv", columns=frozenset({"date", "value", "item"}))) == "yes"
    # a non-csv (a network) is definitely not rankable
    assert spec.check(shape(extension="gexf", columns=frozenset(), columns_are_all=True)) == "no"
    # columns unknown -> rankability unknown -> maybe
    assert spec.check(shape(extension="csv")) == "maybe"


# --- check() against a real dataset is only ever yes/no --------------------

@pytest.mark.parametrize("spec, module, compatible", [
    (Compatibility(types={"a"}), FakeModule(type="a"), True),
    (Compatibility(types={"a"}), FakeModule(type="b"), False),
    (Compatibility(media_types={"image"}), FakeModule(type="x", media_type="image"), True),
    (Compatibility(media_types={"image"}), FakeModule(type="x", media_type="text"), False),
    (Compatibility(extensions={"csv"}), FakeModule(type="x", extension="csv"), True),
    (Compatibility(extensions={"csv"}), FakeModule(type="x", extension="ndjson"), False),
    (Compatibility(top_dataset_only=True), FakeModule(type="x", top=True), True),
    (Compatibility(top_dataset_only=True), FakeModule(type="x", top=False), False),
    (Compatibility(child_only=True), FakeModule(type="x", top=False), True),
    (Compatibility(child_only=True), FakeModule(type="x", top=True), False),
    (Compatibility(excluded_types={"x"}), FakeModule(type="x"), False),
    (Compatibility(datasources={"4chan"}), FakeModule(type="x", datasource="4chan"), True),
    (Compatibility(datasources={"4chan"}), FakeModule(type="x", datasource="reddit"), False),
    (Compatibility(is_collector=True), FakeModule(type="x", from_collector=True), True),
    (Compatibility(is_collector=True), FakeModule(type="x", from_collector=False), False),
])
def test_live_path_behaviour_preserved(spec, module, compatible):
    assert spec.is_compatible_with(module) is compatible


def test_live_check_is_never_maybe():
    # a real dataset knows all its values, so check() is only ever yes/no for a dataset
    spec = Compatibility(media_types={"image"}, extensions={"csv"}, top_dataset_only=True)
    for module in (FakeModule(type="x", media_type="image", extension="csv", top=True),
                   FakeModule(type="x", media_type="text", extension="ndjson", top=False)):
        assert spec.check(DatasetShape(module)) in ("yes", "no")


# --- the output description is honest about what it cannot know ------------

def test_infer_output_honour_traps(logger, fourcat_modules):
    """
    The fallback inference must stay honest on every real processor class: a value not
    set on the class comes out UNKNOWN (never guessed). Tested against _infer_output
    directly, so a processor that declares its own output does not hide a dishonest
    inference.
    """
    from common.lib.outputs import _infer_output
    from common.lib.compatibility import _declared_class_value, _maybe_call, is_collector as is_collector_fn

    for ptype, processor in fourcat_modules.processors.items():
        shape = _infer_output(processor)

        # media: known iff declared on the class (below BasicProcessor), else UNKNOWN
        declared_media = _declared_class_value(processor, "media_type")
        if declared_media:
            assert shape.media == declared_media, f"{ptype}: declared media lost"
        else:
            assert shape.media is UNKNOWN, f"{ptype}: undeclared media is not UNKNOWN"

        # extension: a filter passes its parent's through (UNKNOWN); a value set on the
        # class is trusted; an inherited default stays UNKNOWN, never a confident guess
        is_filter = bool(_maybe_call(processor, "is_filter"))
        declared_ext = _declared_class_value(processor, "extension")
        if is_filter:
            assert shape.extension is UNKNOWN, f"{ptype}: filter extension is not UNKNOWN"
        elif declared_ext:
            assert shape.extension == declared_ext, f"{ptype}: declared extension lost"
        else:
            assert shape.extension is UNKNOWN, f"{ptype}: inherited extension treated as fact"

        # position/collector-ness: a collector is top-level; a filter's result can be made
        # top-level and take on a -search type, so both are UNKNOWN; else a child
        if is_collector_fn(processor):
            assert shape.top_level is True and shape.from_collector is True, f"{ptype}: collector not top"
        elif is_filter:
            assert shape.top_level is UNKNOWN and shape.from_collector is UNKNOWN, f"{ptype}: filter not UNKNOWN"
        else:
            assert shape.top_level is False and shape.from_collector is False, f"{ptype}: not a child"


def test_describe_output_reads_declared_media(logger, fourcat_modules):
    """Cross-check: a media_type set directly on the class must show up as known."""
    from common.lib.outputs import describe_output

    checked = 0
    for processor in fourcat_modules.processors.values():
        own_media = vars(processor).get("media_type")
        if own_media:
            media = describe_output(processor).media
            assert own_media == media or (isinstance(media, set) and own_media in media)
            checked += 1
    logger.info(f"verified {checked} processor(s) that declare media_type directly")


# --- every processor declares its output, and the declaration is truthful ---

def test_every_processor_declares_output(logger, fourcat_modules):
    """The coverage gate: every processor should declare an `output` (an Output, usually
    inherited from a base class). Lists any that still fall back to class inference."""
    from common.lib.outputs import Output

    missing = sorted(ptype for ptype, cls in fourcat_modules.processors.items()
                     if not isinstance(getattr(cls, "output", None), Output))
    logger.info(f"{len(fourcat_modules.processors) - len(missing)} of "
                f"{len(fourcat_modules.processors)} processors declare an output")
    if missing:
        pytest.fail(f"{len(missing)} processor(s) declare no output:\n" + "\n".join(missing))


def test_output_matches_class_attributes(logger, fourcat_modules):
    """Where a processor declares both an `output` and the legacy class attributes, a
    fixed output extension/media must equal the class one -- keeping the declaration
    honest while the legacy attributes still exist (the eventual source to derive from)."""
    from common.lib.outputs import Output
    from common.lib.compatibility import _declared_class_value

    mismatches = []
    for ptype, cls in fourcat_modules.processors.items():
        out = getattr(cls, "output", None)
        if not isinstance(out, Output):
            continue
        shape = out.to_shape(cls)

        declared_ext = _declared_class_value(cls, "extension")
        if declared_ext and isinstance(shape.extension, str) and shape.extension != declared_ext:
            mismatches.append(f"{ptype}: output extension {shape.extension!r} != class {declared_ext!r}")

        declared_media = _declared_class_value(cls, "media_type")
        if declared_media and isinstance(shape.media, str) and shape.media != declared_media:
            mismatches.append(f"{ptype}: output media {shape.media!r} != class {declared_media!r}")

    if mismatches:
        pytest.fail("output does not match class attributes:\n" + "\n".join(sorted(mismatches)))


def test_describe_spec_covers_every_compatibility_axis():
    """
    Every axis a Compatibility can declare must round-trip through describe_spec -- the
    dict the catalogue displays and the map uses as the "requirement" label. Lockstep
    insurance: add an axis without teaching describe_spec and this fails, rather than the
    axis silently vanishing. A field is exempt only when it modifies another axis.
    """
    import dataclasses
    from common.lib.compatibility import describe_spec

    modifiers = {"rankable_multiple_items"}  # tunes `rankable`; not a standalone axis

    def sample(name):
        if name in ("rankable", "is_collector", "top_dataset_only", "child_only"):
            return True
        if name == "required_settings":
            return ["some.setting"]
        return {"x"}

    missing = [field.name for field in dataclasses.fields(Compatibility)
               if field.name not in modifiers
               and field.name not in (describe_spec(Compatibility(**{field.name: sample(field.name)})) or {})]
    assert not missing, ("describe_spec drops these Compatibility axes (add them to "
                         "describe_spec, or to the modifiers exemption): %s" % missing)


# --- the map builds and answers --------------------------------------------

def test_processor_map_builds_and_answers(logger, fourcat_modules):
    from common.lib.processor_map import ProcessorMap

    pmap = ProcessorMap(fourcat_modules, config=None, logger=logger)

    assert set(pmap.processors) == set(fourcat_modules.processors)  # nothing silently dropped

    catalogue = pmap.catalogue()
    assert len(catalogue) == len(fourcat_modules.processors)
    for entry in catalogue:
        assert {"type", "title", "is_datasource", "is_filter", "has_override"} <= set(entry)
        assert "output_shape" not in entry  # browse rows stay light; shape is on the processor view

    total_edges = sum(len(consumers) for consumers in pmap._succ.values())
    assert total_edges > 0, "no edges -- the specs produced an empty map"

    graph = pmap.graph()
    assert graph["nodes"] and isinstance(graph["edges"], list)
    for edge in graph["edges"]:
        assert edge["certainty"] in ("definite", "maybe")

    sample = next(iter(pmap.processors))
    info = pmap.processor(sample)
    assert {"how_to_run", "followups", "compatibility", "output_shape"} <= set(info)
    how_to_run = info["how_to_run"]
    assert "notes" in how_to_run
    if not how_to_run.get("is_filter"):
        assert "accepts" in how_to_run and "examples" in how_to_run
    assert {"preferred", "filters", "others_by_category"} <= set(info["followups"])

    assert isinstance(pmap.search("data"), list)


def test_datasources_are_roots_not_consumers(logger, fourcat_modules):
    """Collectors produce but never consume -- they have no incoming edges."""
    from common.lib.processor_map import ProcessorMap

    pmap = ProcessorMap(fourcat_modules, config=None, logger=logger)
    for ptype, is_root in pmap._collector.items():
        if is_root:
            assert not pmap._pred.get(ptype), f"datasource {ptype} has incoming edges"


# --- the author-facing archetypes ------------------------------------------

class FakeProcessor:
    """A stand-in processor class with just the attributes an Output reads."""

    def __init__(self, type=None, extension="csv"):
        self.type = type
        self.extension = extension


def test_datasource_archetype_uses_class_extension_and_text_media():
    from common.lib.outputs import Datasource
    shape = Datasource().to_shape(FakeProcessor(type="bsky-search", extension="ndjson"))
    assert shape.extension == "ndjson"
    assert shape.media == "text"
    assert shape.top_level is True
    assert shape.from_collector is True
    assert shape.datasource == "bsky"  # a collector carries its datasource in its type
    assert shape.produces_file


def test_datasource_archetype_can_declare_columns():
    from common.lib.outputs import Datasource
    shape = Datasource(columns={"id", "body", "author"}).to_shape(FakeProcessor(type="x-search"))
    assert shape.columns == frozenset({"id", "body", "author"})
    assert Compatibility(requires_all_columns={"author"}).check(shape) == "yes"


def test_filter_archetype_is_passthrough_everywhere():
    from common.lib.outputs import Filter
    shape = Filter().to_shape(FakeProcessor(type="x-filter"))
    assert shape.extension is UNKNOWN
    assert shape.media is UNKNOWN
    assert shape.top_level is UNKNOWN
    assert shape.from_collector is UNKNOWN
    assert shape.columns is UNKNOWN


def test_render_and_network_have_no_columns():
    from common.lib.outputs import Render, Network
    render = Render("svg").to_shape(FakeProcessor(type="x"))
    assert render.extension == "svg"
    assert render.media == "image"
    assert render.columns == frozenset() and render.columns_are_all
    network = Network().to_shape(FakeProcessor(type="x"))
    assert network.extension == "gexf"
    assert network.columns == frozenset() and network.columns_are_all


def test_media_archive_bounded_media_set():
    from common.lib.outputs import MediaArchive
    shape = MediaArchive(media={"image", "video", "audio"}).to_shape(FakeProcessor(type="x"))
    assert shape.extension == "zip"
    assert shape.media == {"image", "video", "audio"}
    # wanting image gets "maybe" (some, not all, of the set matches); wanting text is a no
    assert Compatibility(media_types={"image"}).check(shape) == "maybe"
    assert Compatibility(media_types={"text"}).check(shape) == "no"


def test_no_output_produces_no_file():
    from common.lib.outputs import NoOutput
    assert NoOutput().to_shape(FakeProcessor(type="item-to-annotation")).produces_file is False


def test_describe_output_prefers_declared_over_inference():
    from common.lib.outputs import describe_output, Table

    class Declared(FakeProcessor):
        output = Table(columns={"date", "value", "item"})

    shape = describe_output(Declared(type="x", extension="csv"))
    assert shape.columns == frozenset({"date", "value", "item"})
    assert Compatibility(rankable=True).check(shape) == "yes"  # rankability falls out of the columns
