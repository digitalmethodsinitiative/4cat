"""
Query layer for the processor map: turn the declarative Compatibility + Output specs
into the questions a user-facing catalogue asks -- browse/search, "how do I run this
one" (what it accepts + where to start), and "what can run on its output".

The matcher it builds on lives in common/lib/compatibility.py and the output shapes in
common/lib/outputs.py; this module only builds the producer->consumer graph and reads
it. Computed purely by inspection -- no datasets, no database. Each link carries a
yes/maybe answer.

Two ideas keep the answers readable:

* The declared spec is the label. Rather than re-deriving why a producer matched,
  "how to run" shows the processor's own `describe_spec` (its declared requirement)
  and lists the producers flat, split only on the one honest distinction: a data
  source you start from vs. another processor you run first.
* Filters are transparent. A filter runs on almost any dataset and keeps its format,
  so it never changes what you can run next and can be inserted anywhere. Filters are
  therefore kept out of the normal producer lists and noted separately -- their own
  group under "what can run on this", their own short "how to run".
"""
import logging

from collections import defaultdict

from common.lib.compatibility import (
    Compatibility,
    describe_spec,
    is_collector,
    is_declaratively_compatible,
    UNKNOWN,
)
from common.lib.outputs import describe_output, Filter

_DEFAULT_SPEC = Compatibility(top_dataset_only=True)


def _is_filter(processor):
    """
    Whether a processor is a filter -- it runs on almost anything, keeps its input's
    format, and can be inserted anywhere in a chain. True when it declares a Filter
    output or reports is_filter() (the latter catches filters in the Filtering
    category that do not declare a Filter output).
    """
    if isinstance(getattr(processor, "output", None), Filter):
        return True
    is_filter = getattr(processor, "is_filter", None)
    try:
        return bool(is_filter()) if callable(is_filter) else bool(is_filter)
    except Exception:
        return False


def _required_columns(spec):
    """
    Columns a spec needs present -- the one prerequisite that can't be met by naming a
    producer (any dataset with the columns works). Empty when not column-gated.
    """
    if spec is None:
        return []
    return sorted(set(getattr(spec, "requires_all_columns", None) or [])
                  | set(getattr(spec, "requires_any_columns", None) or []))


def _shape_dict(shape):
    """A producer's output shape as a JSON-friendly dict ('unknown' for what it left open)."""
    def show(value):
        if value is UNKNOWN:
            return "unknown"
        if isinstance(value, (set, frozenset)):
            return sorted(str(item) for item in value)
        return value

    def show_columns(shape):
        if shape.columns is UNKNOWN:
            return "unknown"
        if not shape.columns and shape.columns_are_all:
            return "none"
        return sorted(shape.columns)

    return {
        "type": shape.type,
        "extension": show(shape.extension),
        "media_type": show(shape.media),
        "datasource": show(shape.datasource),
        "top_level": show(shape.top_level),
        "from_collector": show(shape.from_collector),
        "columns": show_columns(shape),
        "produces_file": shape.produces_file,
    }


class ProcessorMap:
    """
    Built once from the loaded modules; answers the catalogue's questions about how
    processors connect, from their declared compatibility + output alone.
    """

    def __init__(self, modules, config=None, logger=None):
        self.config = config
        # The frontend passes its Logger (g.log) so a miscalibrated spec reaches the
        # 4CAT log and, at ERROR, Slack; falls back to stdlib when none is injected.
        self.log = logger or logging.getLogger(__name__)
        self.processors = {}
        self._spec = {}           # declared spec (None when undeclared) -- for display
        self._match_spec = {}     # effective spec used for matching (default if None)
        self._shapes = {}         # producer output shape
        self._collector = {}
        self._declarative = {}
        self._filter = {}         # runs on anything, keeps format, inserted anywhere

        # Build per-processor so one bad processor can't take down the whole map: a
        # `compatibility` that is not a Compatibility (likely a custom extension) is
        # treated as undeclared and logged at ERROR; one that raises is dropped.
        for ptype, processor in (getattr(modules, "processors", {}) or {}).items():
            try:
                spec = getattr(processor, "compatibility", None)
                if spec is not None and not isinstance(spec, Compatibility):
                    self.log.error(
                        "processor map: processor '%s' has a 'compatibility' that is "
                        "%s, not a Compatibility -- treating it as undeclared. The "
                        "spec needs fixing (most likely in a custom extension)."
                        % (ptype, type(spec).__name__))
                    spec = None
                shape = describe_output(processor)
                collector = is_collector(processor)
                declarative = is_declaratively_compatible(processor)
                is_filter = _is_filter(processor)
            except Exception as e:
                self.log.error("processor map: processor '%s' could not be read and "
                               "is omitted from the map: %s" % (ptype, e))
                continue
            self.processors[ptype] = processor
            self._spec[ptype] = spec
            self._match_spec[ptype] = spec if spec is not None else _DEFAULT_SPEC
            self._shapes[ptype] = shape
            self._collector[ptype] = collector
            self._declarative[ptype] = declarative
            self._filter[ptype] = is_filter

        # which processors can follow which (datasources never follow anything). Each
        # link keeps its answer; whether a link is also *approximate* depends on the
        # following processor (it keeps a custom is_compatible_with), tracked per processor.
        self._succ = defaultdict(list)
        self._pred = defaultdict(list)
        self._edge = {}  # (producer, consumer) -> MatchResult
        for ptype in self.processors:
            shape = self._shapes[ptype]
            # a processor that writes no result file (e.g. only annotates its parent)
            # produces nothing for another processor to run on
            if not shape.produces_file:
                continue
            for qtype in self.processors:
                if qtype == ptype or self._collector[qtype]:
                    continue
                try:
                    outcome = self._match_spec[qtype].check(shape)  # "yes" / "maybe" / "no"
                except Exception as e:
                    self.log.warning("processor map: edge %s -> %s skipped: %s" % (ptype, qtype, e))
                    continue
                if outcome != "no":
                    self._succ[ptype].append(qtype)
                    self._pred[qtype].append(ptype)
                    self._edge[(ptype, qtype)] = "definite" if outcome == "yes" else "maybe"

    # -- catalogue / search --

    def _entry(self, ptype):
        processor = self.processors[ptype]
        spec = self._spec[ptype]
        return {
            "type": ptype,
            "title": getattr(processor, "title", ptype),
            "category": getattr(processor, "category", None),
            "description": getattr(processor, "description", None),
            "tags": list(getattr(processor, "tags", []) or []),
            "info": list(getattr(processor, "info", []) or []),
            "warnings": list(getattr(processor, "warnings", []) or []),
            "references": list(getattr(processor, "references", []) or []),
            "icon": getattr(processor, "icon", "") or "",
            "is_datasource": self._collector[ptype],
            "is_filter": self._filter[ptype],
            "has_override": not self._declarative[ptype],
            "requires_dataset_result_file": bool(
                spec is not None and getattr(spec, "requires_dataset_result_file", False)),
        }

    def catalogue(self):
        """Every processor (and datasource), each with display metadata + flags."""
        return [self._entry(ptype) for ptype in self.processors]

    def categories(self):
        """{category: [sorted types]} for grouped browsing."""
        groups = defaultdict(list)
        for ptype in self.processors:
            groups[getattr(self.processors[ptype], "category", None) or "(uncategorised)"].append(ptype)
        return {category: sorted(types) for category, types in sorted(groups.items())}

    def search(self, query):
        """Catalogue entries whose type/title/category/description contains `query`."""
        needle = (query or "").strip().lower()
        if not needle:
            return []
        hits = []
        for ptype in self.processors:
            entry = self._entry(ptype)
            haystack = " ".join(str(entry.get(field) or "") for field in
                                ("type", "title", "category", "description")).lower()
            if needle in haystack:
                hits.append(entry)
        return hits

    # -- one processor --

    def processor(self, ptype):
        """Full bundle for one processor: metadata, spec, how-to-run, follow-ups."""
        if ptype not in self.processors:
            return None
        return {
            **self._entry(ptype),
            "output_shape": _shape_dict(self._shapes[ptype]),
            "compatibility": describe_spec(self._spec[ptype]),
            "how_to_run": self.how_to_run(ptype),
            "followups": self.followups(ptype),
        }

    def _title(self, ptype):
        return getattr(self.processors[ptype], "title", ptype) if ptype in self.processors else ptype

    def _step(self, ptype, certainty=None):
        """A producer step, optionally annotated with the certainty of its link."""
        step = {"type": ptype, "title": self._title(ptype),
                "is_datasource": self._collector.get(ptype, False)}
        if certainty is not None:
            step["certainty"] = certainty
        return step

    def _producers(self, ptype, certainty=None):
        """The processors whose output `ptype` accepts; with `certainty` set
        ("definite" or "maybe"), only the producers whose link has that certainty."""
        producers = []
        for producer in self._pred.get(ptype, []):
            edge = self._edge.get((producer, ptype))
            if certainty is None or edge == certainty:
                producers.append(producer)
        return producers

    # -- how to run one processor --

    def _accepts(self, ptype):
        """
        What `ptype` runs on directly. The declared requirement is the label (its own
        `describe_spec`); the confirmed producers are listed flat, split only on the
        one honest distinction -- a data source you start from vs. another processor
        you run first. Filters are left out: they are transparent (see followups).
        """
        confirmed = self._producers(ptype, "definite")
        datasources = sorted(p for p in confirmed if self._collector[p])
        from_processors = sorted(p for p in confirmed
                                 if not self._collector[p] and not self._filter[p])
        # the declared spec is the label, but only its *input* conditions -- the
        # follow-up hints describe this processor's output, not what it accepts
        requirement = describe_spec(self._spec[ptype]) or {}
        requirement = {key: value for key, value in requirement.items()
                       if key not in ("preferred_followups", "excluded_followups")}
        return {
            "requirement": requirement,
            "datasources": [self._step(p, self._edge.get((p, ptype))) for p in datasources],
            "from_processors": [self._step(p, self._edge.get((p, ptype))) for p in from_processors],
        }

    def _confirmed_producers(self, ptype):
        """Processors and data sources whose output `ptype` definitely accepts, filters
        excluded (they are transparent -- see followups)."""
        return [p for p in self._producers(ptype, "definite") if not self._filter[p]]

    def _match_strength(self, consumer_type, producer_type):
        """
        How fully a producer's output matches what `consumer_type` says it accepts: the
        number of "what kind of input" axes (type, type-prefix, media, datasource) the
        producer definitely satisfies. Used only to order example paths, so a producer built
        for the job (an image downloader for an image step) is preferred over one that
        matches only incidentally (a chart that merely happens to be an image).
        """
        spec = self._match_spec.get(consumer_type)
        shape = self._shapes.get(producer_type)
        if spec is None or shape is None:
            return 0
        strength = 0
        if spec.types and shape.type in set(spec.types):
            strength += 1
        if spec.type_prefixes and shape.type and shape.type.startswith(tuple(spec.type_prefixes)):
            strength += 1
        if spec.media_types and shape.media is not UNKNOWN:
            have = shape.media if isinstance(shape.media, (set, frozenset)) else {shape.media}
            if have and have <= set(spec.media_types):
                strength += 1
        if spec.datasources and shape.datasource is not UNKNOWN and shape.datasource in set(spec.datasources):
            strength += 1
        return strength

    def _examples(self, ptype, count=3):
        """
        A few concrete example paths from a data source to `ptype` -- illustrations of how
        you might reach it, NOT a complete or curated list. Each example is a full chain (a
        data source, the processors to run in order, then `ptype`) and shows a different
        thing to run `ptype` on: one example per direct producer, via the shortest way to
        reach that producer. Producers are ordered by how fully they match `ptype`'s stated
        input (see _match_strength), so a processor built for the job leads and a merely
        incidental match (a chart that happens to be an image, for an image step) shows only
        if nothing better exists. One-per-producer also stops a processor with a single real
        recipe being padded out with longer, roundabout ones. Confirmed links only, filters
        skipped. Empty when nothing reaches `ptype` by confirmed steps (a likely spec gap).
        """
        # Walk producers backward from `ptype`, level by level so the shortest path to each
        # producer surfaces first. `path` is stored tail-first ([node, ..., ptype]); a
        # finished chain (one that reached a data source) drops `ptype` off the tail.
        shortest = {}  # direct producer of ptype -> shortest complete chain ending in it
        frontier = [[ptype]]
        for _ in range(4):  # depth cap; deeper chains are not useful examples
            if not frontier or len(shortest) >= 40:
                break
            nxt = []
            for path in frontier:
                for producer in self._confirmed_producers(path[0]):
                    if producer in path:
                        continue  # don't loop back on a processor already in this path
                    if self._collector[producer]:
                        chain = [producer] + path[:-1]  # reached a data source: chain complete
                        direct = chain[-1]              # the producer `ptype` runs on directly
                        if direct not in shortest or len(chain) < len(shortest[direct]):
                            shortest[direct] = chain
                    else:
                        nxt.append([producer] + path)
            frontier = nxt[:400]  # bound the search; plenty for a few short examples

        ranked = sorted(shortest.values(),
                        key=lambda chain: (-self._match_strength(ptype, chain[-1]),
                                           len(chain), [self._title(step) for step in chain]))
        return [{"datasource": chain[0], "title": self._title(chain[0]),
                 "then": [{"type": step, "title": self._title(step)} for step in chain[1:]]}
                for chain in ranked[:count]]

    def how_to_run(self, ptype):
        """
        How to produce a dataset `ptype` can run on:

        * a filter answers with a single note -- it runs on almost anything and can be
          inserted anywhere, so listing producers would be noise;
        * otherwise `accepts` is what it runs on directly (its declared requirement +
          the confirmed data sources and processors), and `examples` gives a few of the
          shortest full paths from a data source -- concrete illustrations, not a curated
          or complete list of ways to get here;
        * `notes` carries the data-source, filter, column and override caveats.
        """
        if self._filter[ptype]:
            return {
                "type": ptype,
                "is_filter": True,
                "notes": ["This is a filter: it runs on almost any dataset and can be "
                          "inserted at any point in a chain. Its output keeps the same "
                          "format, so it does not change what you can run next."],
            }

        columns = _required_columns(self._spec[ptype])
        notes = []
        if self._collector[ptype]:
            notes.append("This is a data source: it collects data directly (from an upload "
                         "or a query), so it does not run on another dataset.")
        else:
            notes.append("Filters can be applied at any earlier point -- they keep the "
                         "format, so they do not change what this accepts.")
        if columns:
            notes.append("Needs a dataset with these columns (%s); the producing processor "
                         "can't be named from the specs alone." % ", ".join(columns))
        if not self._declarative[ptype]:
            notes.append("Keeps a custom is_compatible_with, so these connections are approximate.")

        return {
            "type": ptype,
            "accepts": self._accepts(ptype),
            "examples": self._examples(ptype),
            "notes": notes,
        }

    def _effective_followups(self, ptype):
        """
        The consumers that can run on `ptype`'s output, as {consumer: certainty}.

        For an ordinary processor this is just its outgoing edges. For a filter it is
        resolved by propagation instead: a filter's output has the same shape as its
        input, so anything that runs on what fed the filter also runs on the filtered
        result. Because a filter accepts almost anything, every data source or processor
        that can reach it is one of its direct producers, so reading its non-filter
        producers (and what runs on each of them) resolves the followups without a walk.
        This turns a filter's followups from the blanket "maybe" its own unknown shape
        gives into the concrete, mostly-definite set it really has.
        """
        if not self._filter[ptype]:
            return {consumer: self._edge[(ptype, consumer)]
                    for consumer in self._succ.get(ptype, [])}
        resolved = {}
        for producer in self._pred.get(ptype, []):
            if self._filter[producer]:
                continue  # another filter gives no concrete shape to propagate
            into_filter = self._edge[(producer, ptype)]
            for consumer in self._succ.get(producer, []):
                if consumer == ptype:
                    continue
                certainty = ("definite" if into_filter == "definite"
                             and self._edge[(producer, consumer)] == "definite" else "maybe")
                if resolved.get(consumer) != "definite":
                    resolved[consumer] = certainty
        return resolved

    def followups(self, ptype):
        """
        What can run on `ptype`'s output: curated `preferred` first, then `filters`
        (kept separate -- a filter can be applied to narrow the data without changing
        its format), then the real analysis steps grouped by category. For a filter the
        set is resolved by propagation (see _effective_followups) and a note explains it.
        """
        spec = self._spec[ptype]
        preferred = [followup for followup in (getattr(spec, "preferred_followups", None) or [])
                     if followup in self.processors]
        preferred_set = set(preferred)
        filters = []
        grouped = defaultdict(list)
        for qtype, certainty in self._effective_followups(ptype).items():
            if qtype in preferred_set:
                continue
            item = {
                "type": qtype,
                "title": getattr(self.processors[qtype], "title", qtype),
                "certainty": certainty,
                "approximate": not self._declarative[qtype],
            }
            if self._filter[qtype]:
                filters.append(item)
            else:
                category = getattr(self.processors[qtype], "category", None) or "(uncategorised)"
                grouped[category].append(item)
        result = {
            "preferred": [self._entry(followup) for followup in preferred],
            "filters": sorted(filters, key=lambda item: item["type"]),
            "others_by_category": {category: sorted(items, key=lambda item: item["type"])
                                   for category, items in sorted(grouped.items())},
        }
        if self._filter[ptype]:
            result["note"] = ("A filter keeps its input's format, so anything you could run on "
                              "the dataset you filtered you can still run here.")
        return result

    def graph(self):
        """
        The whole map as {nodes, edges} -- the producer->consumer backbone the query
        methods traverse, exposed for graph-drawing and debugging. Nodes carry
        `is_root` (alias of is_datasource); edges carry the outcome certainty and
        whether the consumer is approximate (keeps an override).
        """
        nodes = [{**self._entry(ptype), "is_root": self._collector[ptype]} for ptype in self.processors]
        edges = [{"from": producer, "to": consumer,
                  "certainty": self._edge[(producer, consumer)],
                  "approximate": not self._declarative[consumer]}
                 for producer, consumers in self._succ.items() for consumer in consumers]
        return {"nodes": nodes, "edges": edges}
