"""
Plot reduced embeddings in three dimensions: either a 3D reduction, or a 2D
reduction with a column of the original dataset as the third axis.
"""
import datetime
import re

import numpy as np
from dateutil import parser as dateutil_parser

from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException, ProcessorInterruptedException
from common.lib.user_input import UserInput
from processors.machine_learning.embed_media import read_post_id_map
from processors.visualisation.embedding_map import EmbeddingMap

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

# Numbers in a column whose name suggests a time are read as Unix timestamps
# when all of them fall in this range (1973 up to roughly the year 5000). The
# lower bound keeps small counts, like seconds watched, from becoming 1970s
# dates
EPOCH_RANGE = (1e8, 1e11)
TIME_COLUMN = re.compile(r"time|date|created|published", re.IGNORECASE)

# Most tick labels drawn along the third axis
MAX_TICKS = 6


class EmbeddingMap3D(EmbeddingMap):
    """
    Write a self-contained, interactive 3D scatter plot of reduced embeddings.

    A 3D reduction is plotted as is. A 2D reduction is lifted into 3D with a
    column of the original dataset s the height.

    Drawn on a plain 2D canvas rather than with a WebGL library, so the result
    stays a single self-contained file that works when downloaded.
    """
    type = "embedding-map-3d"  # job type ID
    category = "Visual"  # category
    title = "Plot embeddings in 3D"  # title displayed in UI
    description = ("Plot reduced embeddings as an interactive 3D scatter plot. Embeddings reduced to three dimensions "
                   "are plotted as they are. Embeddings reduced to two dimensions get a custom column of the original "
                   "dataset as the third axis (e.g., timestamps). Note that distances in the reduction may be "
                   "meaningless (see references).")
    extension = "html"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on reduced embeddings with two or three dimensions

        :param module: Dataset or processor to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        if getattr(module, "type", None) != "reduce-embeddings":
            return False

        # a processor class has no parameters yet, and can produce either
        if not isinstance(module, DataSet):
            return True

        try:
            return int(module.parameters.get("dimensions", 2)) in (2, 3)
        except (TypeError, ValueError):
            return False

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        The third-axis options only appear for two-dimensional reductions; a
        three-dimensional one already has its third axis.

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        options = super().get_options(parent_dataset=parent_dataset, config=config)

        dimensions = parent_dataset.parameters.get("dimensions") if parent_dataset else None
        if dimensions is not None and str(dimensions) != "2":
            return options

        columns = []
        if parent_dataset:
            columns = parent_dataset.top_parent().get_columns()

        axis_options = {
            "axis_info": {
                "type": UserInput.OPTION_INFO,
                "help": "These embeddings have two dimensions. Choose a column of the original dataset to use as the "
                        "height of each point. Media files that were posted more than once appear once per post.",
            },
            "axis_column": {
                "type": UserInput.OPTION_TEXT,
                "help": "Third axis",
                "default": "timestamp",
                "tooltip": "Column of the original dataset to use as the height of each point, for example a date. "
                           "Items without a value in this column are left out.",
            },
            "axis_spacing": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Third axis spacing",
                "options": {
                    "rank": "Evenly, in sort order",
                    "value": "Proportional to the values (numbers and dates only)",
                },
                "default": "rank",
                "tooltip": "Evenly spaced keeps quiet periods readable when activity comes in bursts; equal values "
                           "always share a height. Proportional spacing shows real distances between values, but "
                           "squeezes sparse stretches together. Text columns are always spaced evenly.",
            },
        }

        if columns:
            axis_options["axis_column"].update({
                "type": UserInput.OPTION_CHOICE,
                "options": {column: column for column in columns},
                "default": "timestamp" if "timestamp" in columns else columns[0],
            })

        options.update(axis_options)
        return options

    def process(self):
        """
        Read the reduced embeddings, add a third axis if needed, and write the
        interactive plot.
        """
        max_text_length = self.parameters.get("max_text_length", 250)
        dimensions = int(self.source_dataset.parameters.get("dimensions", 0) or 0)
        if dimensions not in (2, 3):
            self.dataset.finish_with_error(f"Can only plot embeddings reduced to two or three dimensions, not "
                                           f"{dimensions}.")
            return

        records = []
        self.dataset.update_status("Reading reduced embeddings")
        for item in self.source_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while reading reduced embeddings")

            # the mapped item spreads the coordinates over one column per
            # dimension; the original NDJSON record keeps them as a list
            original = item.original
            if len(original.get("coordinates") or []) != dimensions:
                continue

            text = str(original.get("text", "") or "")
            original["label"] = text[:max_text_length] + ("…" if len(text) > max_text_length else "")
            records.append(original)

        axis = None
        warnings = []
        if dimensions == 3:
            coordinates = np.asarray([record["coordinates"] for record in records], dtype=np.float64)
            points = self.normalise_3d(coordinates) if records else []
            labels = [record["label"] for record in records]
            filenames = [str(record.get("filename", "") or "") for record in records]
            clusters = [record.get("cluster") for record in records]
        else:
            result = self.lift_to_3d(records)
            if result is None:
                return
            points, labels, filenames, clusters, axis, warnings = result

        point_count = len(points)
        if point_count < 3:
            self.dataset.finish_with_error(f"Not enough points to build a plot (found {point_count}, need at least "
                                           f"3).")
            return

        atlas = self.load_sprite(filenames) if any(filenames) else None

        # cluster colours take over from the height colours: the height axis
        # keeps its ticks either way
        colours = None
        if self.parameters.get("colour_clusters", True) and all(cluster is not None for cluster in clusters):
            colours = self.cluster_colours(clusters)
            labels = [f"{label}\n{self.cluster_label(cluster)}" for label, cluster in zip(labels, clusters)]

        self.dataset.update_status("Rendering plot")
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            outfile.write(self.get_html_3d(points, labels, axis, atlas, colours))

        self.dataset.update_status(f"Plotted {point_count:,} points", is_final=True)
        if warnings:
            self.dataset.finish_with_warning(point_count, " ".join(warnings))
        else:
            self.dataset.finish(point_count)

    @staticmethod
    def normalise_3d(coordinates) -> list:
        """
        Fit a 3D reduction into the unit cube, keeping its proportions.

        Scaling every axis by the same factor keeps the shape of the reduction;
        stretching each axis to fill the cube would exaggerate whichever
        direction happened to be flattest.

        :param coordinates:  numpy array of `(x, y, z)` rows
        :return list:  `[x, y, z]` per point, each within 0-1
        """
        mins, maxs = coordinates.min(axis=0), coordinates.max(axis=0)
        span = float((maxs - mins).max()) or 1.0
        normalised = (coordinates - (mins + maxs) / 2) / span + 0.5
        return [[round(float(value), 5) for value in row] for row in normalised]

    def lift_to_3d(self, records: list):
        """
        Give each 2D point a height from a column of the original dataset.

        Text embeddings carry the ID of the post they were made from; media
        embeddings carry the IDs of every post the file appeared in, and get
        one point per post, so a file posted repeatedly shows as a column.

        :param list records:  Reduced embedding records
        :return tuple|None:  `(points, labels, filenames, clusters, axis,
          warnings)`, or `None` after finishing the dataset with an error
        """
        column = self.parameters.get("axis_column") or "timestamp"
        spacing = self.parameters.get("axis_spacing", "rank")

        wanted = set()
        post_id_map = None
        unlinked = 0
        for record in records:
            # media embedded before post IDs were always recorded carry none;
            # the archive's metadata still knows which posts a file came from
            if "filename" in record and not record.get("post_ids"):
                if post_id_map is None:
                    post_id_map = self.load_media_post_ids()
                record["post_ids"] = post_id_map.get(str(record.get("id")), [])

            record["post_ids"] = self.get_post_ids(record)
            if not record["post_ids"]:
                unlinked += 1
            wanted.update(record["post_ids"])

        if unlinked == len(records):
            self.dataset.finish_with_error("None of the items could be linked to a post in the original dataset, so "
                                           "they cannot be given a height from one of its columns.")
            return None

        values = self.read_column(column, wanted)
        if not values:
            self.dataset.finish_with_error(f"None of the items have a value for '{column}' in the original dataset. "
                                           f"Choose another column.")
            return None

        placed, raw_values = [], []
        missing = 0
        for record in records:
            for post_id in record["post_ids"]:
                if post_id not in values:
                    missing += 1
                    continue
                placed.append(record)
                raw_values.append(values[post_id])

        axis = self.build_axis(raw_values, spacing, column)

        # x and y are stretched to the unit square as on the 2D map, so that
        # looking straight down gives the same picture
        coordinates = np.asarray([record["coordinates"] for record in placed], dtype=np.float64)
        mins = coordinates.min(axis=0)
        spans = np.where(coordinates.max(axis=0) - mins == 0, 1, coordinates.max(axis=0) - mins)
        flat = (coordinates - mins) / spans

        points = [[round(float(x), 5), round(float(y), 5), round(height, 5)]
                  for (x, y), height in zip(flat, axis["positions"])]
        labels = [f"{record['label']}\n{column}: {self.shorten(raw)}" for record, raw in zip(placed, raw_values)]
        filenames = [str(record.get("filename", "") or "") for record in placed]
        clusters = [record.get("cluster") for record in placed]

        warnings = []
        if unlinked:
            warnings.append(f"{unlinked:,} files could not be linked to a post in the original dataset and were left "
                            f"out.")
        if missing:
            warnings.append(f"{missing:,} items had no value for '{column}' and were left out.")
        if axis["fallback"]:
            warnings.append(f"'{column}' holds text, so it is spaced evenly in sort order rather than by value.")
        for warning in warnings:
            self.dataset.log(warning)

        return points, labels, filenames, clusters, {"title": column, "ticks": axis["ticks"]}, warnings

    @staticmethod
    def get_post_ids(record: dict) -> list:
        """
        Get the IDs of the posts a reduced embedding stands for.

        A text embedding's own ID is its post's ID. A media file's ID is a hash
        of the file that matches no post, so media only count their `post_ids`.

        :param dict record:  Reduced embedding record
        :return list:  Post IDs as strings, without duplicates
        """
        post_ids = record.get("post_ids") or ([] if "filename" in record else [record.get("id")])
        return list(dict.fromkeys(str(post_id) for post_id in post_ids if post_id is not None))

    def load_media_post_ids(self) -> dict:
        """
        Read which posts each media file came from, from the media archive.

        :return dict:  `{filename without extension: [post ID, ...]}`, empty
          when there is no archive or it has no metadata
        """
        embeddings = self.get_embeddings_dataset(self.source_dataset)
        try:
            archive = embeddings.get_parent() if embeddings else None
        except DataSetException:
            archive = None

        return read_post_id_map(archive.get_results_path() if archive else None, log=self.dataset.log)

    def read_column(self, column: str, wanted: set) -> dict:
        """
        Read one column of the original dataset for the given posts.

        :param str column:  Column to read
        :param set wanted:  IDs of the posts to read it for
        :return dict:  `{post id: value}` for posts with a non-empty value
        """
        values = {}
        seen = set()
        self.dataset.update_status(f"Reading '{column}' from the original dataset")
        for item in self.source_dataset.top_parent().iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while reading the original dataset")

            post_id = str(item.get("id"))
            if post_id not in wanted or post_id in seen:
                continue

            seen.add(post_id)
            value = item.get(column)
            if value is not None and str(value).strip() != "":
                values[post_id] = value

            if len(seen) == len(wanted):
                break

        return values

    @classmethod
    def build_axis(cls, raw_values: list, spacing: str, column: str = "") -> dict:
        """
        Turn column values into heights between 0 and 1, plus tick labels.

        Values are read as numbers, then as dates, and otherwise as text. A
        column that fails either for even one value is treated as text, which
        still sorts ISO dates correctly.

        :param list raw_values:  One value per point
        :param str spacing:  "rank" to space unique values evenly in sort
          order, "value" to space them proportionally (numbers and dates)
        :param str column:  Column name, used to recognise Unix timestamps
        :return dict:  `{positions, ticks, kind, fallback}`
        """
        kind, keys = cls.parse_values(raw_values, column)
        fallback = spacing == "value" and kind == "text"

        unique = sorted(set(keys))
        if spacing == "value" and kind != "text":
            low, high = unique[0], unique[-1]

            def position(key):
                return (key - low) / (high - low) if high != low else 0.5

            position_of = {key: position(key) for key in unique}
            # evenly spread over the range, so the gaps between ticks are equal
            tick_keys = [low + (high - low) * index / (MAX_TICKS - 1) for index in range(MAX_TICKS)] \
                if high != low else [low]
            tick_positions = [position(key) for key in tick_keys]
        else:
            last = len(unique) - 1
            position_of = {key: index / last if last else 0.5 for index, key in enumerate(unique)}
            # an even pick of the actual values, so every tick names a real one
            picks = sorted({round(index * last / (MAX_TICKS - 1)) for index in range(MAX_TICKS)}) if last else [0]
            tick_keys = [unique[index] for index in picks]
            tick_positions = [position_of[key] for key in tick_keys]

        # one date format for all ticks, fine enough to tell them apart
        date_format = "%Y-%m-%d"
        if kind == "date":
            span = unique[-1] - unique[0]
            date_format = "%Y-%m" if span > 2 * 365 * 86400 else "%Y-%m-%d" if span > 2 * 86400 else "%Y-%m-%d %H:%M"

        # text is sorted case-insensitively, but labelled as it was written
        written = {}
        if kind == "text":
            for key, value in zip(keys, raw_values):
                written.setdefault(key, str(value).strip())

        ticks = [[round(position, 5), cls.format_tick(written.get(key, key), kind, date_format)]
                 for position, key in zip(tick_positions, tick_keys)]

        return {
            "positions": [position_of[key] for key in keys],
            "ticks": ticks,
            "kind": kind,
            "fallback": fallback,
        }

    @classmethod
    def parse_values(cls, raw_values: list, column: str = "") -> tuple:
        """
        Work out what kind of values a column holds, and make them sortable.

        :param list raw_values:  Column values
        :param str column:  Column name, used to recognise Unix timestamps
        :return tuple:  `(kind, keys)`, with kind "number", "date" or "text"
          and one sortable key per value
        """
        numbers = []
        for value in raw_values:
            number = cls.to_number(value)
            if number is None:
                break
            numbers.append(number)
        else:
            if TIME_COLUMN.search(column) and all(EPOCH_RANGE[0] < number < EPOCH_RANGE[1] for number in numbers):
                return "date", numbers
            return "number", numbers

        # dates repeat, and dateutil is slow, so parse each distinct value once
        parsed = {}
        dates = []
        for value in raw_values:
            text = str(value).strip()
            if text not in parsed:
                parsed[text] = cls.to_timestamp(text)
            if parsed[text] is None:
                break
            dates.append(parsed[text])
        else:
            return "date", dates

        return "text", [str(value).strip().casefold() for value in raw_values]

    @staticmethod
    def to_number(value) -> float | None:
        """
        Read a value as a number.

        :param value:  Value to read
        :return float|None:  The number, or `None` if it is not one
        """
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if np.isfinite(number) else None

    @staticmethod
    def to_timestamp(text: str) -> float | None:
        """
        Read a value as a date, as seconds since the epoch.

        Dates without a timezone are taken to be UTC, which is how 4CAT writes
        its own timestamps.

        :param str text:  Value to read
        :return float|None:  Timestamp, or `None` if it is not a date
        """
        try:
            moment = datetime.datetime.fromisoformat(text)
        except ValueError:
            # dateutil reads almost anything, including lone words like
            # "may"; a date worth plotting has at least some digits in it
            if not re.search(r"\d", text):
                return None
            try:
                moment = dateutil_parser.parse(text)
            except (ValueError, OverflowError, dateutil_parser.ParserError):
                return None

        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        return moment.timestamp()

    @classmethod
    def format_tick(cls, key, kind: str, date_format: str) -> str:
        """
        Format an axis value for a tick label.

        :param key:  Sortable key, as made by `parse_values()`
        :param str kind:  "number", "date" or "text"
        :param str date_format:  strftime format for dates
        :return str:  Label
        """
        if kind == "date":
            return datetime.datetime.fromtimestamp(key, tz=datetime.timezone.utc).strftime(date_format)
        if kind == "number":
            return f"{key:,.4g}" if abs(key) < 1e15 else f"{key:.3g}"
        return cls.shorten(key)

    @staticmethod
    def shorten(value, length: int = 24) -> str:
        """
        Shorten a value for display.

        :param value:  Value to show
        :param int length:  Maximum length
        :return str:  The value as text, cut off with an ellipsis if too long
        """
        text = str(value)
        return text if len(text) <= length else text[:length - 1] + "…"

    def get_html_3d(self, points: list, labels: list, axis: dict | None, atlas: dict | None = None,
                    colours: dict | None = None) -> str:
        """
        Build the self-contained HTML page.

        Like the 2D map, the result is rendered into a 4CAT page as well as
        opened directly when downloaded, so it has no `<html>`/`<body>` wrapper,
        scopes its CSS to one container and keeps its JavaScript in an IIFE.

        :param list points:  `[x, y, z]` per point, each within 0-1
        :param list labels:  Hover text per point, in the same order
        :param dict|None axis:  `{title, ticks}` when the height is a column
          of the original dataset, `None` for a 3D reduction
        :param dict atlas:  Sprite sheet from `load_sprite()`, or `None` to draw
          plain dots
        :param dict colours:  Cluster colours from `cluster_colours()`, or
          `None` to colour by height (or not at all, for a 3D reduction)
        :return str:  HTML
        """
        payload = self.encode_payload({"points": points, "labels": labels, "axis": axis, **(colours or {})}, atlas)

        container = f"embedding-map-3d-{self.dataset.key}"
        algorithm = self.source_dataset.parameters.get("algorithm", "umap").upper()
        subtitle = f"{len(points):,} points &middot; {algorithm}"
        if axis:
            # the column name is user-chosen; keep it out of the markup
            subtitle += " &middot; height: " + axis["title"].replace("&", "&amp;").replace("<", "&lt;")
        if atlas:
            drawn = sum(1 for tile in atlas["tiles"] if tile > -1)
            subtitle += f" &middot; {drawn:,} thumbnails"
        if colours:
            subtitle += " &middot; coloured by cluster"

        return HTML_TEMPLATE_3D % {"container": container, "payload": payload, "subtitle": subtitle}


HTML_TEMPLATE_3D = """<meta charset="utf-8">
<div id="%(container)s" class="embedding-map-3d">
<style>
#%(container)s { position: relative; width: 100%%; height: 80vh; min-height: 420px; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fbfbfc; border: 1px solid #dcdce0; box-sizing: border-box; overflow: hidden; }
#%(container)s canvas { display: block; width: 100%%; height: 100%%; cursor: grab; }
#%(container)s canvas.dragging { cursor: grabbing; }
#%(container)s canvas.clickable { cursor: pointer; }
#%(container)s .em-bar { position: absolute; top: 0; left: 0; right: 0; display: flex; flex-wrap: wrap; gap: 6px; justify-content: space-between; align-items: center; padding: 8px 12px; font-size: 12px; color: #55555c; background: linear-gradient(#fbfbfcef, #fbfbfc00); pointer-events: none; }
#%(container)s .em-buttons { display: flex; flex-wrap: wrap; gap: 4px; }
#%(container)s .em-bar button { pointer-events: auto; font: inherit; font-size: 11px; padding: 3px 9px; border: 1px solid #cacad0; border-radius: 3px; background: #fff; color: #33333a; cursor: pointer; }
#%(container)s .em-bar button:hover { background: #f0f0f3; }
#%(container)s .em-bar button[aria-pressed="true"] { background: #33333a; border-color: #33333a; color: #fff; }
#%(container)s .em-hint { position: absolute; bottom: 8px; right: 12px; font-size: 11px; color: #8a8a92; pointer-events: none; }
#%(container)s .em-legend { position: absolute; bottom: 10px; left: 12px; font-size: 11px; color: #55555c; pointer-events: none; }
#%(container)s .em-legend .em-ramp { width: 160px; height: 8px; margin: 3px 0 2px; border-radius: 2px; }
#%(container)s .em-legend .em-ends { display: flex; justify-content: space-between; width: 160px; }
#%(container)s .em-legend .em-key { display: flex; align-items: center; gap: 6px; line-height: 1.6; }
#%(container)s .em-legend .em-swatch { flex: none; width: 9px; height: 9px; border-radius: 50%%; }
#%(container)s .em-tip { position: absolute; max-width: 320px; padding: 8px 10px; font-size: 12px; line-height: 1.45; color: #1c1c20; background: #fff; border: 1px solid #cacad0; border-radius: 4px; box-shadow: 0 2px 10px #00000026; pointer-events: none; opacity: 0; transition: opacity .1s; white-space: pre-wrap; overflow-wrap: anywhere; z-index: 2; }
#%(container)s .em-tip.visible { opacity: 1; }
</style>
<div class="em-bar"><span>%(subtitle)s</span><span class="em-buttons">
<button type="button" data-preset="angled">Angled</button><button type="button" data-preset="top">Top</button><button type="button" data-preset="side">Side</button><button type="button" data-preset="front">Front</button>
<button type="button" data-perspective aria-pressed="false">Perspective</button><button type="button" data-reset>Reset view</button>
</span></div>
<canvas></canvas>
<div class="em-legend" hidden></div>
<div class="em-hint">drag to rotate, shift-drag to pan, scroll to zoom</div>
<div class="em-tip"></div>
</div>
<script>
(function () {
    var root = document.getElementById("%(container)s");
    if (!root || root.dataset.ready) return;
    root.dataset.ready = "1";

    var data = %(payload)s;
    var points = data.points, labels = data.labels, axis = data.axis, count = points.length;
    var tiles = data.tiles || null, tileSize = data.tile || 0, atlasCols = data.cols || 1;
    var files = data.files || null, linkBase = data.base || "";

    // the address of the media behind a point, or "" when there is none
    function linkFor(i) {
        if (!files || !linkBase || i < 0 || !files[i]) return "";
        return linkBase + encodeURIComponent(files[i]);
    }
    var atlas = null;
    if (data.atlas) {
        atlas = new Image();
        atlas.onload = function () { requestDraw(); };
        atlas.src = data.atlas;
    }

    var canvas = root.querySelector("canvas"), ctx = canvas.getContext("2d");
    var tip = root.querySelector(".em-tip");
    var RADIUS = 3.2, DEG = Math.PI / 180, CAMERA = 2.2;
    var PRESETS = {angled: [-35, 25], top: [0, 90], side: [0, 0], front: [-90, 0]};
    var view, width = 0, height = 0, hovered = -1, pending = false;

    // screen position, depth and perspective factor per point, from the last
    // draw; hovering reads these so it always matches what is on screen
    var screenX = new Float32Array(count), screenY = new Float32Array(count);
    var depth = new Float32Array(count), factor = new Float32Array(count);
    var order = new Uint32Array(count);
    for (var o = 0; o < count; o++) order[o] = o;

    // when the height is a column, colour follows it too: colour survives
    // rotation, height does not. Viridis, bucketed so each draw only switches
    // between a few fill styles.
    var STOPS = [[68, 1, 84], [59, 82, 139], [33, 145, 140], [94, 201, 98], [253, 231, 37]];
    function ramp(t) {
        var s = Math.min(STOPS.length - 2, Math.floor(t * (STOPS.length - 1)));
        var f = t * (STOPS.length - 1) - s, a = STOPS[s], b = STOPS[s + 1];
        return [0, 1, 2].map(function (c) { return Math.round(a[c] + (b[c] - a[c]) * f); });
    }
    var BUCKETS = 48, fills = [], bucket = null;
    if (data.colour) {
        // coloured by cluster instead: an index into the cluster palette
        fills = data.palette; bucket = data.colour;
    } else if (axis) {
        for (var k = 0; k < BUCKETS; k++) fills.push("rgba(" + ramp(k / (BUCKETS - 1)).join(",") + ",0.8)");
        bucket = new Uint8Array(count);
        for (var p = 0; p < count; p++) bucket[p] = Math.round(points[p][2] * (BUCKETS - 1));
    }

    function reset() {
        view = {yaw: PRESETS.angled[0], pitch: PRESETS.angled[1], scale: 1, x: 0, y: 0,
                perspective: view ? view.perspective : false};
    }
    reset();

    function resize() {
        var dpr = window.devicePixelRatio || 1, box = canvas.getBoundingClientRect();
        width = box.width; height = box.height;
        canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        draw();
    }

    function requestDraw() {
        if (pending) return;
        pending = true;
        window.requestAnimationFrame(function () { pending = false; draw(); });
    }

    // The cube is centred on the origin with the third axis pointing up. Yaw
    // turns it around that axis, pitch tilts the camera from level (0, looking
    // from the side) to straight down (90, which gives the 2D map).
    var cam = {};
    function setCamera() {
        cam.cy = Math.cos(view.yaw * DEG); cam.sy = Math.sin(view.yaw * DEG);
        cam.cp = Math.cos(view.pitch * DEG); cam.sp = Math.sin(view.pitch * DEG);
        cam.fit = Math.min(width, height) * 0.62 * view.scale;
        cam.ox = width / 2 + view.x; cam.oy = height / 2 + view.y;
    }

    // world coordinates (each -0.5 to 0.5) -> [screen x, screen y, depth, scale]
    function toScreen(x, y, z) {
        var x1 = x * cam.cy - y * cam.sy, y1 = x * cam.sy + y * cam.cy;
        var up = y1 * cam.sp + z * cam.cp, d = y1 * cam.cp - z * cam.sp;
        var f = view.perspective ? CAMERA / (CAMERA + d) : 1;
        return [cam.ox + x1 * f * cam.fit, cam.oy - up * f * cam.fit, d, f];
    }

    function thumbScale() {
        return Math.max(14, Math.min(tileSize, 16 * view.scale));
    }

    function drawTile(i, x, y, drawn) {
        var tile = tiles[i];
        if (tile < 0 || !atlas || !atlas.complete) {
            ctx.beginPath(); ctx.arc(x, y, RADIUS * factor[i], 0, 6.2832); ctx.fill();
            return;
        }
        var sx = (tile %% atlasCols) * tileSize, sy = Math.floor(tile / atlasCols) * tileSize;
        ctx.drawImage(atlas, sx, sy, tileSize, tileSize, x - drawn / 2, y - drawn / 2, drawn, drawn);
        // outline the thumbnail in its cluster's colour; items in no cluster
        // (the last palette entry) get none
        if (data.colour && data.colour[i] < data.palette.length - 1) {
            ctx.strokeStyle = data.palette[data.colour[i]].slice(0, 7); ctx.lineWidth = 2;
            ctx.strokeRect(x - drawn / 2, y - drawn / 2, drawn, drawn);
        }
    }

    function line(a, b) {
        ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
    }

    // a box, a floor grid and ticks along the height: without them a rotating
    // cloud gives no sense of which way is up
    function drawGuides() {
        var h = 0.5, g, i;
        ctx.lineWidth = 1;
        ctx.strokeStyle = "#e8e8ec";
        for (i = 1; i < 4; i++) {
            g = -h + i / 4;
            line(toScreen(g, -h, -h), toScreen(g, h, -h));
            line(toScreen(-h, g, -h), toScreen(h, g, -h));
        }
        ctx.strokeStyle = "#d2d2d8";
        var corners = [[-h, -h], [h, -h], [h, h], [-h, h]];
        for (i = 0; i < 4; i++) {
            var a = corners[i], b = corners[(i + 1) %% 4];
            line(toScreen(a[0], a[1], -h), toScreen(b[0], b[1], -h));
            line(toScreen(a[0], a[1], h), toScreen(b[0], b[1], h));
            line(toScreen(a[0], a[1], -h), toScreen(a[0], a[1], h));
        }

        // ticks only make sense when the height axis is visible at all
        if (!axis || Math.abs(cam.cp) < 0.2) return;

        // label the vertical edge furthest to the left, so labels sit outside
        var edge = corners[0], leftmost = Infinity;
        for (i = 0; i < 4; i++) {
            var foot = toScreen(corners[i][0], corners[i][1], -h)[0];
            if (foot < leftmost) { leftmost = foot; edge = corners[i]; }
        }
        ctx.fillStyle = "#55555c"; ctx.font = "11px sans-serif";
        ctx.textAlign = "right"; ctx.textBaseline = "middle";
        ctx.strokeStyle = "#a8a8b0";
        axis.ticks.forEach(function (tick) {
            var at = toScreen(edge[0], edge[1], tick[0] - h);
            line([at[0] - 5, at[1]], at);
            ctx.fillText(tick[1], at[0] - 8, at[1]);
        });
        var top = toScreen(edge[0], edge[1], h);
        ctx.textAlign = "center"; ctx.textBaseline = "bottom"; ctx.font = "bold 11px sans-serif";
        ctx.fillText(axis.title, top[0], top[1] - 8);
    }

    function draw() {
        setCamera();
        ctx.clearRect(0, 0, width, height);
        drawGuides();

        var i, s;
        for (i = 0; i < count; i++) {
            s = toScreen(points[i][0] - 0.5, points[i][1] - 0.5, points[i][2] - 0.5);
            screenX[i] = s[0]; screenY[i] = s[1]; depth[i] = s[2]; factor[i] = s[3];
        }
        // painter's algorithm: furthest first, so nearer points cover them
        order.sort(function (a, b) { return depth[b] - depth[a]; });

        var drawn = tiles ? thumbScale() : 0, margin = tiles ? drawn : 10, fill = -1;
        ctx.fillStyle = "rgba(40, 92, 168, 0.6)";
        for (var n = 0; n < count; n++) {
            i = order[n];
            if (i === hovered) continue;
            var x = screenX[i], y = screenY[i];
            if (x < -margin || x > width + margin || y < -margin || y > height + margin) continue;
            if (bucket && bucket[i] !== fill) { fill = bucket[i]; ctx.fillStyle = fills[fill]; }
            if (tiles) drawTile(i, x, y, drawn * factor[i]);
            else { ctx.beginPath(); ctx.arc(x, y, RADIUS * factor[i], 0, 6.2832); ctx.fill(); }
        }

        if (hovered > -1) {
            var hx = screenX[hovered], hy = screenY[hovered];
            if (tiles) {
                var big = Math.min(tileSize * 1.5, drawn * 1.8);
                drawTile(hovered, hx, hy, big);
                ctx.strokeStyle = "#d2451e"; ctx.lineWidth = 2;
                ctx.strokeRect(hx - big / 2, hy - big / 2, big, big);
            } else {
                ctx.fillStyle = "#d2451e";
                ctx.beginPath(); ctx.arc(hx, hy, RADIUS + 2.5, 0, 6.2832); ctx.fill();
                ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke();
            }
        }
    }

    // the point under the cursor nearest the camera, so a point hidden behind
    // another is never the one that gets picked
    function nearest(mx, my) {
        var best = -1, bestDepth = Infinity;
        var reach = tiles ? Math.max(12, thumbScale() / 2) : 12, limit = reach * reach;
        for (var i = 0; i < count; i++) {
            var dx = screenX[i] - mx, dy = screenY[i] - my;
            if (dx * dx + dy * dy < limit && depth[i] < bestDepth) { bestDepth = depth[i]; best = i; }
        }
        return best;
    }

    function hideTip() {
        hovered = -1; tip.classList.remove("visible");
    }

    var drag = {active: false, moved: false};
    canvas.addEventListener("mousedown", function (e) {
        var box = canvas.getBoundingClientRect();
        drag = {active: true, moved: false, pan: e.shiftKey || e.button === 2,
                startX: e.clientX - box.left, startY: e.clientY - box.top,
                yaw: view.yaw, pitch: view.pitch, x: view.x, y: view.y};
        canvas.classList.add("dragging");
        hideTip();
    });
    canvas.addEventListener("contextmenu", function (e) { e.preventDefault(); });
    window.addEventListener("mouseup", function () {
        drag.active = false; canvas.classList.remove("dragging");
    });

    canvas.addEventListener("mousemove", function (e) {
        var box = canvas.getBoundingClientRect(), mx = e.clientX - box.left, my = e.clientY - box.top;
        if (drag.active) {
            var dx = mx - drag.startX, dy = my - drag.startY;
            if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;
            if (drag.pan) { view.x = drag.x + dx; view.y = drag.y + dy; }
            else {
                view.yaw = drag.yaw + dx * 0.4;
                view.pitch = Math.max(-90, Math.min(90, drag.pitch + dy * 0.4));
            }
            requestDraw(); return;
        }
        var found = nearest(mx, my);
        canvas.classList.toggle("clickable", !!linkFor(found));
        if (found !== hovered) {
            hovered = found;
            if (found > -1) {
                tip.textContent = labels[found] || "(no text)";
                tip.classList.add("visible");
            } else tip.classList.remove("visible");
            requestDraw();
        }
        if (hovered > -1) {
            var tw = tip.offsetWidth, th = tip.offsetHeight;
            tip.style.left = Math.min(Math.max(8, mx + 14), Math.max(8, width - tw - 8)) + "px";
            tip.style.top = (my - th - 12 < 8 ? my + 18 : my - th - 12) + "px";
        }
    });

    canvas.addEventListener("mouseleave", function () { hideTip(); requestDraw(); });

    canvas.addEventListener("wheel", function (e) {
        e.preventDefault();
        var box = canvas.getBoundingClientRect(), mx = e.clientX - box.left, my = e.clientY - box.top;
        var step = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        var next = Math.min(Math.max(view.scale * step, 0.3), 40);
        step = next / view.scale;
        // zoom toward the cursor, so the point under it stays put
        var ox = width / 2 + view.x, oy = height / 2 + view.y;
        view.x = mx - (mx - ox) * step - width / 2;
        view.y = my - (my - oy) * step - height / 2;
        view.scale = next;
        hideTip(); requestDraw();
    }, {passive: false});

    canvas.addEventListener("click", function (e) {
        if (drag.moved) return;
        var box = canvas.getBoundingClientRect();
        var url = linkFor(nearest(e.clientX - box.left, e.clientY - box.top));
        if (url) window.open(url, "_blank", "noopener");
    });

    root.querySelectorAll("[data-preset]").forEach(function (button) {
        button.addEventListener("click", function () {
            var preset = PRESETS[button.dataset.preset];
            view.yaw = preset[0]; view.pitch = preset[1];
            hideTip(); requestDraw();
        });
    });

    var perspective = root.querySelector("[data-perspective]");
    perspective.addEventListener("click", function () {
        view.perspective = !view.perspective;
        perspective.setAttribute("aria-pressed", String(view.perspective));
        hideTip(); requestDraw();
    });

    root.querySelector("[data-reset]").addEventListener("click", function () {
        reset(); hideTip(); requestDraw();
    });

    if (data.legend && data.legend.length) {
        var keys = root.querySelector(".em-legend");
        data.legend.forEach(function (entry) {
            var key = document.createElement("div"), swatch = document.createElement("span");
            key.className = "em-key"; swatch.className = "em-swatch"; swatch.style.background = entry[1];
            // textContent, not markup: the legend is built from the data
            key.appendChild(swatch); key.appendChild(document.createTextNode(entry[0]));
            keys.appendChild(key);
        });
        keys.hidden = false;
    } else if (axis && axis.ticks.length) {
        var legend = root.querySelector(".em-legend"), stops = [];
        for (var r = 0; r <= 4; r++) stops.push("rgb(" + ramp(r / 4).join(",") + ")");
        var title = document.createElement("div"), bar = document.createElement("div");
        var ends = document.createElement("div"), first = document.createElement("span");
        var last = document.createElement("span");
        // textContent, not markup: the column name and values come from the data
        title.textContent = "Colour: " + axis.title;
        bar.className = "em-ramp"; bar.style.background = "linear-gradient(to right, " + stops.join(",") + ")";
        ends.className = "em-ends";
        first.textContent = axis.ticks[0][1]; last.textContent = axis.ticks[axis.ticks.length - 1][1];
        ends.appendChild(first); ends.appendChild(last);
        legend.appendChild(title); legend.appendChild(bar); legend.appendChild(ends);
        legend.hidden = false;
    }

    window.addEventListener("resize", resize);
    resize();
})();
</script>
"""
