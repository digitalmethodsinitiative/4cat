"""
Plot how far embeddings are from a reference over time to map how 'stable' embeddings stay.
"""
import datetime
from collections import defaultdict

import numpy as np

from common.lib.embeddings import find_embedding, normalise_in_place, read_embedding_matrix
from common.lib.exceptions import QueryParametersException
from common.lib.user_input import UserInput
from processors.machine_learning.embedding_similarity import embed_query
from processors.visualisation.embedding_map import (CLUSTER_PALETTE, CLUSTERED_EMBEDDINGS, EMBEDDING_TYPES,
                                                    MAX_TICKS, NOISE_COLOUR, OTHER_CLUSTERS_COLOUR, EmbeddingMap)

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

# Units items can be sliced into time windows by
TIME_WINDOWS = {
    "second": "Seconds",
    "minute": "Minutes",
    "hour": "Hours",
    "day": "Days",
    "month": "Months",
    "year": "Years",
}

# What the zero line can stand for
REFERENCES = {
    "centre": "Centre",
    "medoid": "Most typical item (medoid)",
    "first_window": "Centre of the first time window",
    "previous_window": "Centre of the previous time window",
    "text": "A text prompt",
    "item": "A specific item",
}

# Values that put an item in the bottom half when splitting by a column;
# anything else that is present counts as true
FALSE_VALUES = {"false", "no", "0", "none", "null", "n", "f"}

# Colour of points and trend lines when not coloured by cluster
DEFAULT_COLOUR = "#285ca8"


class EmbeddingStreams(EmbeddingMap):
    """
    Plot each embedding's cosine distance to a reference against time.

    The reference is the zero line through the middle of the plot; distance
    grows towards the top and bottom. Which half an item is drawn in can carry
    a yes/no column of the original dataset, or alternate when it should not
    mean anything. Trend lines follow the median distance per time window, so
    a stream that drifts away from its reference visibly widens.
    """
    type = "embedding-streams"  # job type ID
    category = "Visual"  # category
    title = "Embedding streams"  # title displayed in UI
    description = ("Plot how far embeddings are from a reference embedding over time. This can show the 'stream' of "
                   "variability and durability of a set of embeddings.")
    extension = "html"  # extension of result file, used internally and in UI

    references = [
        "[Cosine similarity](https://en.wikipedia.org/wiki/Cosine_similarity)",
    ]

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on embeddings, clustered or not

        Unlike the other plots, this one works with the full embeddings rather
        than a reduction: distances are measured in the space the model made.

        :param module: Dataset or processor to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return getattr(module, "type", None) in (*EMBEDDING_TYPES, CLUSTERED_EMBEDDINGS)

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        columns = cls.get_top_columns(parent_dataset)

        def column_option(help_text: str, tooltip: str, default: str = "") -> dict:
            # a picker when the original dataset's columns are known, else text
            option = {"type": UserInput.OPTION_TEXT, "help": help_text, "default": default, "tooltip": tooltip}
            if columns:
                option.update({
                    "type": UserInput.OPTION_CHOICE,
                    "options": {column: column for column in columns},
                    "default": default if default in columns else columns[0],
                })
            return option

        options = {
            "time_info": {
                "type": UserInput.OPTION_INFO,
                "help": "The x axis is the time determined by the original dataset, and the y axis is a cosine "
                        "distance from a reference embedding. Media files posted more than once "
                        "appear once per post.",
            },
            "time_column": column_option("Time column", "Column of the original dataset with the date and time to "
                                                        "place each item at. Items without one are left out.",
                                         "timestamp"),
            "time_window": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Time window",
                "options": TIME_WINDOWS,
                "default": "day",
                "tooltip": "Used for trend lines.",
            },
            "reference": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Measure distance to",
                "options": REFERENCES,
                "default": "centre",
                "tooltip": "For all embeddings or per cluster if 'Use clusters' has been ran on the parent dataset."
            },
            "reference_text": {
                "type": UserInput.OPTION_TEXT,
                "help": "Text embedding",
                "default": "",
                "tooltip": "Text is embedded using the same model as the items.",
                "requires": "reference==text",
            },
            "reference_item": {
                "type": UserInput.OPTION_TEXT,
                "help": "Item ID",
                "default": "",
                "tooltip": "The ID of an item ('id') in the original dataset; for media, any post the "
                           "file appeared in.",
                "requires": "reference==item",
            },
            "split": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Top or bottom half",
                "options": {
                    "alternate": "Alternating",
                    "column": "Based on binary value",
                },
                "default": "alternate",
                "tooltip": "The zero line is in the middle and items are placed above and below it to suggest a "
                           "'stream'. This option lets you select what determines the split.",
            },
            "split_column": {
                **column_option("Split by column", "Column of the original dataset that decides top/bottom placement."),
                "requires": "split==column",
            },
            "trend_lines": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Trend lines",
                "default": True,
                "tooltip": "Shows a line representing the median distance per time window with a band from the 25th to "
                           "the 75th percentile.",
            },
        }

        if cls.has_clusters(parent_dataset):
            options["use_clusters"] = {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Use clusters (a zero line per cluster)",
                "default": True,
                "tooltip": "Give each cluster its own zero line and trend lines. Deselect to place all embeddings on one stream.",
            }
            options["clusters"] = {
                "type": UserInput.OPTION_TEXT,
                "help": "Clusters to include",
                "default": "",
                "tooltip": "Cluster numbers separated by commas, e.g. '0, 2, 5'. Leave empty for all. -1 is the "
                           "items that fit no cluster.",
                "requires": "use_clusters==true",
            }

        # the hover text length, cluster colours, sizes and thumbnails work as
        # in the other plots
        shared = super().get_options(parent_dataset=parent_dataset, config=config)
        shared.pop("colour_clusters_info", None)
        options.update(shared)

        return options

    @classmethod
    def validate_query(cls, query, request, config):
        """
        Validate input

        :param dict query:  Query parameters, as submitted by the user via the web interface
        :param request:  Flask request
        :param ConfigManager config:  Configuration reader
        :return dict:  Validated query parameters
        """
        if query.get("reference") == "text" and not str(query.get("reference_text", "")).strip():
            raise QueryParametersException("Enter a text prompt to measure distance to.")

        if query.get("reference") == "item" and not str(query.get("reference_item", "")).strip():
            raise QueryParametersException("Enter the ID of the item to measure distance to.")

        try:
            cls.parse_clusters(query.get("clusters", ""))
        except ValueError:
            raise QueryParametersException("Clusters to include must be cluster numbers separated by commas, e.g. "
                                           "'0, 2, 5'.")

        return query

    @staticmethod
    def parse_clusters(text) -> set | None:
        """
        Read the clusters to include.

        :param text:  Comma-separated cluster numbers, or empty for all
        :return set|None:  Cluster numbers, or `None` for all
        :raises ValueError:  If a part is not a whole number
        """
        parts = [part.strip() for part in str(text or "").split(",") if part.strip()]
        return {int(part) for part in parts} or None

    @staticmethod
    def is_true(value) -> bool:
        """
        Read a column value as yes or no.

        :param value:  Value from the original dataset
        :return bool:  `False` for 'false', 'no', 0 and empty values; `True`
          for 'true', 'yes', 'x' and any other value that is present
        """
        if value is None or isinstance(value, bool):
            return bool(value)

        text = str(value).strip().casefold()
        if text in ("", *FALSE_VALUES):
            return False

        try:
            return float(text) != 0
        except ValueError:
            return True

    @staticmethod
    def window_of(timestamp: float, unit: str) -> int:
        """
        Get the time window a moment falls in.

        :param float timestamp:  Seconds since the epoch, UTC
        :param str unit:  One of `TIME_WINDOWS`
        :return int:  A number that is the same for every moment in the
          window, and grows with time
        """
        if unit in ("second", "minute", "hour"):
            return int(timestamp // {"second": 1, "minute": 60, "hour": 3600}[unit])

        moment = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
        if unit == "month":
            return moment.year * 12 + moment.month - 1
        if unit == "year":
            return moment.year
        return moment.date().toordinal()

    @staticmethod
    def window_start(window: int, unit: str) -> float:
        """
        Get the moment a time window starts, the inverse of `window_of()`.

        :param int window:  Window number from `window_of()`
        :param str unit:  One of `TIME_WINDOWS`
        :return float:  Seconds since the epoch, UTC
        """
        if unit in ("second", "minute", "hour"):
            return float(window * {"second": 1, "minute": 60, "hour": 3600}[unit])

        if unit == "month":
            moment = datetime.datetime(window // 12, window % 12 + 1, 1)
        elif unit == "year":
            moment = datetime.datetime(window, 1, 1)
        else:
            moment = datetime.datetime.fromordinal(window)
        return moment.replace(tzinfo=datetime.timezone.utc).timestamp()

    @classmethod
    def window_ticks(cls, times, unit: str) -> list:
        """
        Put time axis ticks at the starts of the time windows.

        Evenly spaced moments would fall mid-window and get labels that skip
        windows; window starts line up with how the trend lines are sliced.

        :param times:  Timestamp per point
        :param str unit:  One of `TIME_WINDOWS`
        :return list:  `[x, label]` per tick, x within 0-1
        """
        low, high = float(min(times)), float(max(times))
        span = (high - low) or 1.0
        label_format = {"second": "%H:%M:%S", "minute": "%m-%d %H:%M", "hour": "%m-%d %H:%M", "day": "%Y-%m-%d",
                        "month": "%Y-%m", "year": "%Y"}.get(unit, "%Y-%m-%d")

        first, last = cls.window_of(low, unit), cls.window_of(high, unit)
        starts = [cls.window_start(window, unit) for window in range(first, last + 2)]
        starts = [start for start in starts if low <= start <= high]
        if not starts:
            return [[0.0, cls.format_tick(low, "date", label_format)]]

        # too many windows to label: an even pick of them
        step = max(1, int(np.ceil(len(starts) / (MAX_TICKS * 2))))
        return [[round((start - low) / span, 6), cls.format_tick(start, "date", label_format)]
                for start in starts[::step]]

    def process(self):
        """
        Read the embeddings, place them in time, measure their distance to the
        reference, and write the interactive plot.
        """
        parameters = self.parameters
        max_text_length = parameters.get("max_text_length", 250)
        reference = parameters.get("reference", "centre")
        reference_item = str(parameters.get("reference_item", "") or "").strip()
        use_clusters = bool(parameters.get("use_clusters", False))
        try:
            wanted_clusters = self.parse_clusters(parameters.get("clusters", "")) if use_clusters else None
        except ValueError:
            self.dataset.finish_with_error("Clusters to include must be cluster numbers separated by commas.")
            return

        # read embeddings
        def accept(record):
            return wanted_clusters is None or record.get("cluster") in wanted_clusters

        def keep(record):
            # what is needed per item later on, but never the vector itself
            text = str(record.get("text", "") or "")
            summary = {key: record[key] for key in ("id", "filename", "post_ids", "cluster") if key in record}
            summary["label"] = text[:max_text_length] + ("…" if len(text) > max_text_length else "")
            return summary

        self.dataset.update_status("Reading embeddings")
        try:
            matrix, _, records = read_embedding_matrix(self.source_dataset, self.source_dataset.num_rows, self,
                                                       accept=accept, keep=keep)
        except ValueError:
            self.dataset.finish_with_error("The parent dataset contains embeddings of different sizes, so they "
                                           "cannot be compared.")
            return

        if len(records) < 3:
            self.dataset.finish_with_error(f"Not enough embeddings to plot (found {len(records)}, need at least 3).")
            return

        normalise_in_place(matrix)

        # the reference item counts even if its cluster is left out, so it is
        # looked up among all embeddings rather than the ones read above
        reference_vector, reference_record_id = None, None
        if reference == "item":
            reference_vector, found = find_embedding(self.source_dataset,
                                                     lambda record: self.matches_item(record, reference_item), self)
            if found is not None:
                if len(reference_vector) != matrix.shape[1]:
                    self.dataset.finish_with_error("The reference item's embedding has a different size from the "
                                                   "others', so they cannot be compared.")
                    return
                reference_record_id = str(found.get("id"))

        # place items in time
        if self.link_posts(records) == len(records):
            self.dataset.finish_with_error("None of the items could be linked to a post in the original dataset, so "
                                           "they cannot be placed in time.")
            return

        # an item ID that is a post the file was in, for media embedded before
        # post IDs were always recorded
        if reference == "item" and reference_vector is None:
            for index, record in enumerate(records):
                if reference_item in record["post_ids"]:
                    reference_vector, reference_record_id = matrix[index], str(record.get("id"))
                    break

        time_column = parameters.get("time_column") or "timestamp"
        split_column = parameters.get("split_column") if parameters.get("split") == "column" else None
        size_column = parameters.get("size_column")
        wanted = {post_id for record in records for post_id in record["post_ids"]}
        rows = self.read_columns([time_column, split_column, size_column], wanted)

        point_records, raw_times, raw_splits, raw_sizes = [], [], [], []
        missing = 0
        for index, record in enumerate(records):
            for post_id in record["post_ids"]:
                row = rows.get(post_id, {})
                if time_column not in row:
                    missing += 1
                    continue
                point_records.append(index)
                raw_times.append(row[time_column])
                raw_splits.append(row.get(split_column))
                raw_sizes.append(row.get(size_column))

        if not point_records:
            self.dataset.finish_with_error(f"None of the items have a value for '{time_column}' in the original "
                                           f"dataset. Choose another time column.")
            return

        kind, times = self.parse_values(raw_times, time_column)
        if kind != "date":
            self.dataset.finish_with_error(f"'{time_column}' does not hold dates or times, so items cannot be placed "
                                           f"in time. Choose another time column.")
            return

        point_records = np.asarray(point_records)
        times = np.asarray(times, dtype=np.float64)
        unit = parameters.get("time_window", "day")
        windows = np.asarray([self.window_of(moment, unit) for moment in times])

        # one stream, unless 'Use clusters' is on: then one reference per cluster
        per_cluster = use_clusters and all(record.get("cluster") is not None for record in records)
        record_groups = np.asarray([record.get("cluster", 0) if per_cluster else 0 for record in records])
        groups = record_groups[point_records]

        # measure distances
        self.dataset.update_status("Measuring distances")
        if reference == "text":
            embeddings = self.get_embeddings_dataset(self.source_dataset)
            vector, _, error = embed_query(self.config, embeddings.parameters.get("model") if embeddings else None,
                                           str(parameters.get("reference_text", "")).strip(), log=self.log)
            if error:
                self.dataset.finish_with_error(error)
                return
            if len(vector) != matrix.shape[1]:
                self.dataset.finish_with_error("The text prompt's embedding has a different size from the items', so "
                                               "they cannot be compared.")
                return
            reference_vector = vector

        if reference == "item" and reference_vector is None:
            self.dataset.finish_with_error(f"No item with ID '{reference_item}' was found among the embeddings.")
            return

        distances, marked, excluded = self.measure(matrix, reference, reference_vector, record_groups, point_records,
                                                   groups, windows)
        if reference == "item":
            marked = [index for index in range(len(point_records))
                      if str(records[point_records[index]].get("id")) == reference_record_id]

        keep = ~np.isnan(distances)
        if keep.sum() < 3:
            self.dataset.finish_with_error("Not enough items could be measured against the reference to build a plot.")
            return

        # everything per kept point, in time order
        order = np.flatnonzero(keep)[np.argsort(times[keep], kind="stable")]
        renumber = {old: new for new, old in enumerate(order)}
        marked = sorted(renumber[index] for index in marked if index in renumber)

        point_records, times, windows, groups = point_records[order], times[order], windows[order], groups[order]
        distances = distances[order]
        raw_times = [raw_times[index] for index in order]
        raw_splits = [raw_splits[index] for index in order]
        raw_sizes = [raw_sizes[index] for index in order]

        if split_column:
            sides = [1 if self.is_true(value) else -1 for value in raw_splits]
            halves = {"top": f"{split_column}: yes", "bottom": f"{split_column}: no"}
        else:
            # alternate within each cluster: alternating over all points would
            # put a whole cluster in one half whenever clusters post in step
            counts = defaultdict(int)
            sides = []
            for group in groups:
                sides.append(1 if counts[group] % 2 == 0 else -1)
                counts[group] += 1
            halves = {"top": "alternating", "bottom": "alternating"}

        axis = self.build_axis(raw_times, "value", time_column)
        extent = max(1.0, float(distances.max()))

        # clusters can colour the points even when they share one reference
        clusters = None
        if all(record.get("cluster") is not None for record in records):
            clusters = [int(records[index]["cluster"]) for index in point_records]
        colours = None
        if clusters is not None and parameters.get("colour_clusters", True):
            colours = self.cluster_colours(clusters)

        labels = []
        for index, record_index in enumerate(point_records):
            label = records[record_index]["label"]
            label += f"\n{self.format_tick(times[index], 'date', '%Y-%m-%d %H:%M')}"
            label += f"\ndistance: {distances[index]:.3f}"
            if clusters is not None:
                label += f"\n{self.cluster_label(clusters[index])}"
            if split_column:
                label += f"\n{split_column}: {self.shorten(raw_splits[index] if raw_splits[index] is not None else '')}"
            if index in marked:
                label += ("\n(the reference)" if reference == "item"
                          else "\n(this cluster's medoid)" if per_cluster else "\n(the medoid)")
            labels.append(label)

        sizes = None
        if size_column:
            sizes = self.size_factors(raw_sizes, parameters.get("size_scale", "log"))
            if sizes is None:
                self.dataset.log(f"Not sizing by '{size_column}': it holds no numbers.")

        trend = []
        if parameters.get("trend_lines", True):
            trend = self.trend_lines(axis["positions"], distances, sides, groups, windows,
                                     colour_by_cluster=per_cluster and colours is not None)

        filenames = [str(records[index].get("filename", "") or "") for index in point_records]
        atlas = self.load_sprite(filenames) if any(filenames) else None

        warnings = []
        if missing:
            warnings.append(f"{missing:,} posts had no value for '{time_column}' and were left out.")
        if excluded:
            window = "each cluster's first time window" if per_cluster else "the first time window"
            warnings.append(f"{excluded:,} items in {window} have no previous window to compare with and were left "
                            f"out.")
        for warning in warnings:
            self.dataset.log(warning)

        self.dataset.update_status("Rendering plot")
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            outfile.write(self.get_html_streams(
                [[round(position, 6), round(float(distance), 5), side]
                 for position, distance, side in zip(axis["positions"], distances, sides)],
                labels, self.window_ticks(times, unit), extent, halves, trend, marked, atlas, colours, sizes))

        point_count = len(order)
        self.dataset.update_status(f"Plotted {point_count:,} points", is_final=True)
        if warnings:
            self.dataset.finish_with_warning(point_count, " ".join(warnings))
        else:
            self.dataset.finish(point_count)

    @staticmethod
    def matches_item(record: dict, item_id: str) -> bool:
        """
        Whether an embedding record is the item the user asked for.

        :param dict record:  Embedding record
        :param str item_id:  ID given by the user: the item's own, or a post's
        :return bool:  Whether the record matches
        """
        if not item_id:
            return False
        if str(record.get("id")) == item_id:
            return True
        return item_id in [str(post_id) for post_id in record.get("post_ids") or []]

    def measure(self, matrix, reference: str, reference_vector, record_groups, point_records, groups,
                windows) -> tuple:
        """
        Measure each point's cosine distance to its reference.

        Distances are computed per embedding and then shared by its posts, so
        a file posted many times is not multiplied in memory.

        :param matrix:  Normalised embeddings, one row per record
        :param str reference:  One of `REFERENCES`
        :param reference_vector:  The vector for 'text' and 'item' references
        :param record_groups:  Cluster per record (all 0 without clusters)
        :param point_records:  Record per point
        :param groups:  Cluster per point
        :param windows:  Time window per point
        :return tuple:  `(distances, marked, excluded)`: a distance per point
          (NaN where there is none), the points to mark as a cluster's medoid,
          and how many points had no previous window
        """
        distances = np.full(len(point_records), np.nan)
        marked, excluded = [], 0

        def distance_to(record_indices, vector):
            vector = np.asarray(vector, dtype=np.float32)
            vector = vector / (np.linalg.norm(vector) or 1)
            return 1.0 - matrix[record_indices] @ vector

        if reference in ("text", "item"):
            per_record = distance_to(np.arange(len(matrix)), reference_vector)
            return per_record[point_records], marked, excluded

        for group in np.unique(groups):
            points = np.flatnonzero(groups == group)
            group_records = np.unique(point_records[points])

            if reference in ("centre", "medoid"):
                centre = matrix[group_records].mean(axis=0)
                if reference == "medoid":
                    # the item closest to the centre: a true medoid compares
                    # every item with every other, which does not scale
                    medoid = group_records[np.argmax(matrix[group_records] @ centre)]
                    centre = matrix[medoid]
                    marked.extend(points[point_records[points] == medoid].tolist())

                per_record = dict(zip(group_records, distance_to(group_records, centre)))
                distances[points] = [per_record[record] for record in point_records[points]]
                continue

            # references that depend on time: a centre per window
            group_windows = sorted(set(windows[points].tolist()))
            centres = {window: matrix[np.unique(point_records[points[windows[points] == window]])].mean(axis=0)
                       for window in group_windows}

            for position, window in enumerate(group_windows):
                in_window = points[windows[points] == window]
                if reference == "first_window":
                    centre = centres[group_windows[0]]
                elif position == 0:
                    excluded += len(in_window)
                    continue
                else:
                    centre = centres[group_windows[position - 1]]

                window_records = np.unique(point_records[in_window])
                per_record = dict(zip(window_records, distance_to(window_records, centre)))
                distances[in_window] = [per_record[record] for record in point_records[in_window]]

        return distances, marked, excluded

    @staticmethod
    def trend_lines(positions, distances, sides, groups, windows, colour_by_cluster: bool) -> list:
        """
        Summarise each cluster's distances per time window, per half.

        :param positions:  Horizontal position per point, 0-1
        :param distances:  Distance per point
        :param sides:  1 for the top half, -1 for the bottom half, per point
        :param groups:  Cluster per point
        :param windows:  Time window per point
        :param bool colour_by_cluster:  Whether lines take their cluster's colour
        :return list:  `{colour, side, points}` per line, with `points` a list
          of `[x, median, 25th percentile, 75th percentile]`, in time order
        """
        bins = defaultdict(list)
        for index, (group, side, window) in enumerate(zip(groups, sides, windows)):
            bins[(int(group), side, int(window))].append(index)

        lines = defaultdict(list)
        for (group, side, window), indices in sorted(bins.items(), key=lambda entry: entry[0][2]):
            values = np.asarray([distances[index] for index in indices])
            lines[(group, side)].append([
                round(float(np.median([positions[index] for index in indices])), 6),
                round(float(np.median(values)), 5),
                round(float(np.percentile(values, 25)), 5),
                round(float(np.percentile(values, 75)), 5),
            ])

        def colour_of(group):
            if not colour_by_cluster:
                return DEFAULT_COLOUR
            if group < 0:
                return NOISE_COLOUR
            return CLUSTER_PALETTE[group] if group < len(CLUSTER_PALETTE) else OTHER_CLUSTERS_COLOUR

        return [{"colour": colour_of(group), "side": side, "points": sorted(points)}
                for (group, side), points in sorted(lines.items())]

    def describe_reference(self) -> str:
        """
        Describe the reference for the subtitle and axis.

        :return str:  Short description, not yet escaped
        """
        reference = self.parameters.get("reference", "centre")
        if reference == "text":
            return f"text prompt '{self.shorten(str(self.parameters.get('reference_text', '')).strip(), 40)}'"
        if reference == "item":
            return f"item {self.parameters.get('reference_item', '')}"

        description = REFERENCES.get(reference, reference).lower()
        if self.parameters.get("use_clusters"):
            description += ", per cluster"
        return description

    def get_html_streams(self, points: list, labels: list, ticks: list, extent: float, halves: dict, trend: list,
                         marked: list, atlas: dict | None = None, colours: dict | None = None,
                         sizes: list | None = None) -> str:
        """
        Build the self-contained HTML page.

        Like the other plots, the result is rendered into a 4CAT page as well as
        opened directly when downloaded, so it has no `<html>`/`<body>` wrapper,
        scopes its CSS to one container and keeps its JavaScript in an IIFE.

        :param list points:  `[x, distance, side]` per point: x within 0-1, side
          1 for the top half and -1 for the bottom half
        :param list labels:  Hover text per point
        :param list ticks:  `[x, label]` time axis ticks
        :param float extent:  Largest distance the vertical axis shows
        :param dict halves:  What the top and bottom halves stand for
        :param list trend:  Trend lines from `trend_lines()`
        :param list marked:  Indices of points to mark as the reference
        :param dict atlas:  Sprite sheet from `load_sprite()`, or `None`
        :param dict colours:  Cluster colours from `cluster_colours()`, or `None`
        :param list sizes:  Size factor per point, or `None`
        :return str:  HTML
        """
        reference = self.describe_reference()
        payload = self.encode_payload({
            "points": points, "labels": labels, "ticks": ticks, "extent": extent, "halves": halves, "trend": trend,
            "marked": marked, "sizes": sizes, "reference": reference,
            "markedLabel": "reference" if self.parameters.get("reference") == "item" else "medoid",
            **(colours or {}),
        }, atlas)

        container = f"embedding-streams-{self.dataset.key}"
        window = TIME_WINDOWS.get(self.parameters.get("time_window", "day"), "").lower()
        subtitle = (f"{len(points):,} points &middot; distance to {self.escape(reference)} &middot; "
                    f"{self.escape(window)} windows")
        if atlas:
            drawn = sum(1 for tile in atlas["tiles"] if tile > -1)
            subtitle += f" &middot; {drawn:,} thumbnails"
        if colours:
            subtitle += " &middot; coloured by cluster"
        if sizes:
            subtitle += " &middot; sized by " + self.escape(self.parameters.get("size_column"))

        return HTML_TEMPLATE_STREAMS % {"container": container, "payload": payload, "subtitle": subtitle}


HTML_TEMPLATE_STREAMS = """<meta charset="utf-8">
<div id="%(container)s" class="embedding-streams">
<style>
#%(container)s { position: relative; width: 100%%; height: 80vh; min-height: 420px; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fbfbfc; border: 1px solid #dcdce0; box-sizing: border-box; overflow: hidden; }
#%(container)s canvas { display: block; width: 100%%; height: 100%%; cursor: grab; }
#%(container)s canvas.dragging { cursor: grabbing; }
#%(container)s canvas.clickable { cursor: pointer; }
#%(container)s .em-bar { position: absolute; top: 0; left: 0; right: 0; display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; font-size: 12px; color: #55555c; background: linear-gradient(#fbfbfcef, #fbfbfc00); pointer-events: none; }
#%(container)s .em-bar button { pointer-events: auto; font: inherit; font-size: 11px; padding: 3px 9px; border: 1px solid #cacad0; border-radius: 3px; background: #fff; color: #33333a; cursor: pointer; }
#%(container)s .em-bar button:hover { background: #f0f0f3; }
#%(container)s .em-tip { position: absolute; max-width: 320px; padding: 8px 10px; font-size: 12px; line-height: 1.45; color: #1c1c20; background: #fff; border: 1px solid #cacad0; border-radius: 4px; box-shadow: 0 2px 10px #00000026; pointer-events: none; opacity: 0; transition: opacity .1s; white-space: pre-wrap; overflow-wrap: anywhere; z-index: 2; }
#%(container)s .em-tip.visible { opacity: 1; }
#%(container)s .em-legend { position: absolute; bottom: 44px; right: 14px; max-height: 45%%; overflow-y: auto; padding: 6px 8px; font-size: 11px; line-height: 1.6; color: #33333a; background: #fbfbfcd9; border-radius: 4px; pointer-events: none; }
#%(container)s .em-key { display: flex; align-items: center; gap: 6px; }
#%(container)s .em-swatch { flex: none; width: 9px; height: 9px; border-radius: 50%%; }
#%(container)s .em-swatch.em-ring { background: none; border: 2px solid #1c1c20; box-sizing: border-box; }
</style>
<div class="em-bar"><span>%(subtitle)s &middot; scroll to zoom, drag to pan</span><button type="button" data-reset>Reset view</button></div>
<canvas></canvas>
<div class="em-legend" hidden></div>
<div class="em-tip"></div>
</div>
<script>
(function () {
    var root = document.getElementById("%(container)s");
    if (!root || root.dataset.ready) return;
    root.dataset.ready = "1";

    var data = %(payload)s;
    var points = data.points, labels = data.labels, extent = data.extent || 1;
    var tiles = data.tiles || null, tileSize = data.tile || 0, atlasCols = data.cols || 1;
    var files = data.files || null, linkBase = data.base || "";
    var colour = data.colour || null, palette = data.palette || null;
    var sizes = data.sizes || null;
    var marked = {};
    (data.marked || []).forEach(function (i) { marked[i] = true; });
    function sizeOf(i) { return sizes ? sizes[i] : 1; }

    function linkFor(i) {
        if (!files || !linkBase || i < 0 || !files[i]) return "";
        return linkBase + encodeURIComponent(files[i]);
    }
    var atlas = null;
    if (data.atlas) {
        atlas = new Image();
        atlas.onload = function () { draw(); };
        atlas.src = data.atlas;
    }

    var canvas = root.querySelector("canvas"), ctx = canvas.getContext("2d");
    var tip = root.querySelector(".em-tip");
    // room for the axes: distance labels on the left, dates at the bottom
    var RADIUS = 3.2, LEFT = 58, RIGHT = 18, TOP = 40, BOTTOM = 36;
    var view = {scale: 1, x: 0, y: 0}, width = 0, height = 0, hovered = -1;

    function resize() {
        var dpr = window.devicePixelRatio || 1, box = canvas.getBoundingClientRect();
        width = box.width; height = box.height;
        canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        draw();
    }

    // time (0-1) and signed distance -> canvas pixels: the reference is the
    // horizontal middle, distance grows towards the top and the bottom
    function toScreen(x, distance, side) {
        var plotW = width - LEFT - RIGHT, plotH = height - TOP - BOTTOM;
        var y = 0.5 - side * Math.min(distance, extent) / extent / 2;
        return [LEFT + x * plotW * view.scale + view.x, TOP + y * plotH * view.scale + view.y];
    }
    function project(i) { return toScreen(points[i][0], points[i][1], points[i][2]); }

    function thumbScale() {
        return Math.max(14, Math.min(tileSize, 16 * view.scale));
    }

    function drawTile(i, xy, drawn) {
        var tile = tiles[i];
        if (tile < 0 || !atlas || !atlas.complete) {
            ctx.beginPath(); ctx.arc(xy[0], xy[1], RADIUS * sizeOf(i), 0, 6.2832); ctx.fill();
            return;
        }
        var sx = (tile %% atlasCols) * tileSize, sy = Math.floor(tile / atlasCols) * tileSize;
        ctx.drawImage(atlas, sx, sy, tileSize, tileSize, xy[0] - drawn / 2, xy[1] - drawn / 2, drawn, drawn);
        // outline the thumbnail in its cluster's colour; items in no cluster
        // (the last palette entry) get none
        if (colour && colour[i] < palette.length - 1) {
            ctx.strokeStyle = palette[colour[i]].slice(0, 7); ctx.lineWidth = 2;
            ctx.strokeRect(xy[0] - drawn / 2, xy[1] - drawn / 2, drawn, drawn);
        }
    }

    function line(x1, y1, x2, y2) {
        ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    }

    function drawAxes() {
        var plotBottom = height - BOTTOM;
        ctx.font = "11px sans-serif"; ctx.fillStyle = "#55555c"; ctx.lineWidth = 1;

        // distance gridlines, mirrored around the reference
        ctx.textAlign = "right"; ctx.textBaseline = "middle";
        var steps = [0.25, 0.5, 0.75, 1];
        if (extent > 1) steps.push(extent);
        steps.forEach(function (d) {
            [1, -1].forEach(function (side) {
                var y = toScreen(0, d, side)[1];
                if (y < TOP || y > plotBottom) return;
                ctx.strokeStyle = "#ececf0"; line(LEFT, y, width - RIGHT, y);
                ctx.fillText(d.toFixed(2), LEFT - 6, y);
            });
        });

        // the reference itself
        var mid = toScreen(0, 0, 1)[1];
        if (mid >= TOP && mid <= plotBottom) {
            ctx.strokeStyle = "#33333a"; ctx.lineWidth = 1.5; line(LEFT, mid, width - RIGHT, mid);
            ctx.fillText("0", LEFT - 6, mid);
        }

        // what the halves stand for
        ctx.textAlign = "left"; ctx.fillStyle = "#8a8a92";
        ctx.fillText("\\u25b2 " + data.halves.top, LEFT + 6, TOP + 10);
        ctx.fillText("\\u25bc " + data.halves.bottom, LEFT + 6, plotBottom - 10);

        // time ticks
        ctx.fillStyle = "#55555c"; ctx.textAlign = "center"; ctx.textBaseline = "top"; ctx.lineWidth = 1;
        data.ticks.forEach(function (tick) {
            var x = toScreen(tick[0], 0, 1)[0];
            if (x < LEFT || x > width - RIGHT) return;
            ctx.strokeStyle = "#ececf0"; line(x, TOP, x, plotBottom);
            ctx.fillText(tick[1], x, plotBottom + 8);
        });

        ctx.save(); ctx.translate(14, (TOP + plotBottom) / 2); ctx.rotate(-Math.PI / 2);
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillText("cosine distance to " + data.reference, 0, 0);
        ctx.restore();
    }

    function drawTrend() {
        (data.trend || []).forEach(function (trend) {
            var pts = trend.points;
            if (!pts.length) return;
            // the band from the 25th to the 75th percentile
            ctx.beginPath();
            pts.forEach(function (p, k) {
                var xy = toScreen(p[0], p[3], trend.side);
                if (k) ctx.lineTo(xy[0], xy[1]); else ctx.moveTo(xy[0], xy[1]);
            });
            for (var k = pts.length - 1; k >= 0; k--) {
                var xy = toScreen(pts[k][0], pts[k][2], trend.side);
                ctx.lineTo(xy[0], xy[1]);
            }
            ctx.closePath(); ctx.fillStyle = trend.colour + "26"; ctx.fill();
        });
    }

    function drawMedians() {
        (data.trend || []).forEach(function (trend) {
            var pts = trend.points;
            if (pts.length < 2) return;
            // a white edge under the line keeps it readable over dense points
            [["#ffffff", 4], [trend.colour, 2]].forEach(function (style) {
                ctx.strokeStyle = style[0]; ctx.lineWidth = style[1];
                ctx.beginPath();
                pts.forEach(function (p, k) {
                    var xy = toScreen(p[0], p[1], trend.side);
                    if (k) ctx.lineTo(xy[0], xy[1]); else ctx.moveTo(xy[0], xy[1]);
                });
                ctx.stroke();
            });
        });
    }

    // the medoid or reference item: a dark ring around the dot, or a dark
    // frame around the thumbnail
    function drawMark(i, xy, drawn) {
        ctx.strokeStyle = "#1c1c20"; ctx.lineWidth = 3;
        if (tiles && tiles[i] > -1) {
            ctx.strokeRect(xy[0] - drawn / 2 - 3, xy[1] - drawn / 2 - 3, drawn + 6, drawn + 6);
        } else {
            ctx.beginPath(); ctx.arc(xy[0], xy[1], RADIUS * sizeOf(i) + 4, 0, 6.2832); ctx.stroke();
        }
        ctx.fillStyle = "#1c1c20"; ctx.font = "bold 10px sans-serif";
        ctx.textAlign = "left"; ctx.textBaseline = "bottom";
        ctx.fillText(data.markedLabel, xy[0] + (tiles ? drawn / 2 : 6) + 3, xy[1] - 3);
    }

    function draw() {
        ctx.clearRect(0, 0, width, height);
        drawAxes();

        // keep the data inside the plot area while zoomed or panned
        ctx.save();
        ctx.beginPath(); ctx.rect(LEFT, TOP, width - LEFT - RIGHT, height - TOP - BOTTOM); ctx.clip();
        drawTrend();

        ctx.fillStyle = "rgba(40, 92, 168, 0.55)";
        var drawn = tiles ? thumbScale() : 0, fill = -1;
        // two passes when there are thumbnails: dots first, so thumbnails are
        // always drawn on top of them
        for (var pass = tiles ? 0 : 1; pass < 2; pass++) {
            for (var i = 0; i < points.length; i++) {
                if (i === hovered) continue;
                if (tiles && (tiles[i] > -1) !== (pass === 1)) continue;
                var xy = project(i);
                if (xy[0] < LEFT - 30 || xy[0] > width + 30 || xy[1] < TOP - 30 || xy[1] > height + 30) continue;
                if (colour && colour[i] !== fill) { fill = colour[i]; ctx.fillStyle = palette[fill]; }
                if (tiles) drawTile(i, xy, drawn * sizeOf(i));
                else { ctx.beginPath(); ctx.arc(xy[0], xy[1], RADIUS * sizeOf(i), 0, 6.2832); ctx.fill(); }
            }
        }

        drawMedians();
        Object.keys(marked).forEach(function (key) {
            var i = +key;
            drawMark(i, project(i), drawn * sizeOf(i));
        });

        if (hovered > -1) {
            var h = project(hovered);
            if (tiles) {
                var big = Math.min(tileSize * 1.5, drawn * 1.8) * sizeOf(hovered);
                drawTile(hovered, h, big);
                ctx.strokeStyle = "#d2451e"; ctx.lineWidth = 2;
                ctx.strokeRect(h[0] - big / 2, h[1] - big / 2, big, big);
            } else {
                ctx.fillStyle = "#d2451e";
                ctx.beginPath(); ctx.arc(h[0], h[1], RADIUS * sizeOf(hovered) + 2.5, 0, 6.2832); ctx.fill();
                ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke();
            }
        }
        ctx.restore();
    }

    function nearest(mx, my) {
        var best = -1, bestDist = 144;
        for (var i = 0; i < points.length; i++) {
            var xy = project(i);
            var d = (xy[0] - mx) * (xy[0] - mx) + (xy[1] - my) * (xy[1] - my);
            if (d < bestDist) { bestDist = d; best = i; }
        }
        return best;
    }

    var drag = {active: false, moved: false, startX: 0, startY: 0, viewX: 0, viewY: 0};
    canvas.addEventListener("mousemove", function (e) {
        var box = canvas.getBoundingClientRect(), mx = e.clientX - box.left, my = e.clientY - box.top;
        if (drag.active) {
            if (Math.abs(mx - drag.startX) > 3 || Math.abs(my - drag.startY) > 3) drag.moved = true;
            view.x = drag.viewX + (mx - drag.startX); view.y = drag.viewY + (my - drag.startY);
            draw(); return;
        }
        var found = nearest(mx, my);
        canvas.classList.toggle("clickable", !!linkFor(found));
        if (found !== hovered) {
            hovered = found;
            if (found > -1) {
                tip.textContent = labels[found] || "(no text)";
                tip.classList.add("visible");
            } else tip.classList.remove("visible");
            draw();
        }
        if (hovered > -1) {
            var tw = tip.offsetWidth, th = tip.offsetHeight;
            tip.style.left = Math.min(Math.max(8, mx + 14), Math.max(8, width - tw - 8)) + "px";
            tip.style.top = (my - th - 12 < 8 ? my + 18 : my - th - 12) + "px";
        }
    });

    canvas.addEventListener("mouseleave", function () {
        hovered = -1; tip.classList.remove("visible"); draw();
    });

    canvas.addEventListener("wheel", function (e) {
        e.preventDefault();
        var box = canvas.getBoundingClientRect(), mx = e.clientX - box.left, my = e.clientY - box.top;
        var factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        var next = Math.min(Math.max(view.scale * factor, 0.5), 60);
        factor = next / view.scale;
        // zoom toward the cursor, so the point under it stays put
        view.x = (mx - LEFT) - ((mx - LEFT) - view.x) * factor;
        view.y = (my - TOP) - ((my - TOP) - view.y) * factor;
        view.scale = next;
        draw();
    }, {passive: false});

    canvas.addEventListener("mousedown", function (e) {
        var box = canvas.getBoundingClientRect();
        drag = {active: true, moved: false, startX: e.clientX - box.left, startY: e.clientY - box.top,
                viewX: view.x, viewY: view.y};
        canvas.classList.add("dragging");
        tip.classList.remove("visible"); hovered = -1;
    });
    window.addEventListener("mouseup", function () {
        drag.active = false; canvas.classList.remove("dragging");
    });

    canvas.addEventListener("click", function (e) {
        if (drag.moved) return;
        var box = canvas.getBoundingClientRect();
        var url = linkFor(nearest(e.clientX - box.left, e.clientY - box.top));
        if (url) window.open(url, "_blank", "noopener");
    });

    root.querySelector("[data-reset]").addEventListener("click", function () {
        view = {scale: 1, x: 0, y: 0};
        hovered = -1; tip.classList.remove("visible");
        draw();
    });

    var legend = root.querySelector(".em-legend"), entries = (data.legend || []).slice();
    if (data.marked && data.marked.length) entries.push(["the " + data.markedLabel, null]);
    if (entries.length) {
        entries.forEach(function (entry) {
            var key = document.createElement("div"), swatch = document.createElement("span");
            key.className = "em-key"; swatch.className = "em-swatch";
            if (entry[1]) swatch.style.background = entry[1]; else swatch.classList.add("em-ring");
            // textContent, not markup: the legend is built from the data
            key.appendChild(swatch); key.appendChild(document.createTextNode(entry[0]));
            legend.appendChild(key);
        });
        legend.hidden = false;
    }

    window.addEventListener("resize", resize);
    resize();
})();
</script>
"""
