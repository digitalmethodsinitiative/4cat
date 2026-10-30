"""
Plot two-dimensional reduced embeddings as an interactive map.
"""
import datetime
import json
import re
from collections import Counter

import numpy as np
from dateutil import parser as dateutil_parser

from backend.lib.processor import BasicProcessor
from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException, ProcessorInterruptedException
from common.lib.user_input import UserInput
from processors.machine_learning.embed_media import read_post_id_map
from processors.visualisation.media_thumbnails import MediaThumbnails

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

# Datasets whose items are media files, and so can be shown as thumbnails
MEDIA_EMBEDDINGS = ("image-embeddings", "video-embeddings", "audio-embeddings")

# Datasets the embeddings themselves were made in, as opposed to later steps
# (clustering, reduction) that carry them along
EMBEDDING_TYPES = ("text-embeddings", *MEDIA_EMBEDDINGS)

# Numbers in a column whose name suggests a time are read as Unix timestamps
# when all of them fall in this range (1973 up to roughly the year 5000). The
# lower bound keeps small counts, like seconds watched, from becoming 1970s
# dates
EPOCH_RANGE = (1e8, 1e11)
TIME_COLUMN = re.compile(r"time|date|created|published", re.IGNORECASE)

# Most tick labels drawn along an axis
MAX_TICKS = 6

# Most steps walked up the chain of parent datasets
MAX_ANCESTRY = 25

# Smallest and largest size factor for 'Size by', relative to a normal dot or
# thumbnail
SIZE_RANGE = (0.6, 2.4)

# Embeddings with a cluster per item, made by the 'Cluster embeddings'
# processor; sits between the embeddings and their reduction
CLUSTERED_EMBEDDINGS = "cluster-embeddings"

# Colours for the largest clusters, in fixed order: cluster 0 (the largest)
# always gets the first. More clusters share one neutral colour rather than
# cycling, which would give different clusters the same colour
CLUSTER_PALETTE = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948")
OTHER_CLUSTERS_COLOUR = "#8a8a92"
NOISE_COLOUR = "#c4c4cc"


class EmbeddingMap(BasicProcessor):
    """
    Write a self-contained, interactive HTML scatter plot of embeddings that
    were reduced to two dimensions by the 'Reduce dimensions of embeddings'
    processor.
    """
    type = "embedding-map"  # job type ID
    category = "Visual"  # category
    title = "Plot embeddings"  # title displayed in UI
    description = ("Plot embeddings that were reduced to two dimensions as an interactive map, so items with similar "
                   "meanings sit near each other. Note that distances may be meaningless (see references).")
    extension = "html"  # extension of result file, used internally and in UI

    references = [
        "[Understanding UMAP](https://pair-code.github.io/understanding-umap/)",
        "[How to Use t-SNE Effectively](https://distill.pub/2016/misread-tsne/)",
    ]

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on reduced embeddings with exactly two dimensions

        A map has two axes, so anything else would either drop dimensions or
        need a projection of its own; neither belongs here.

        :param module: Dataset or processor to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        if getattr(module, "type", None) != "reduce-embeddings":
            return False

        # a processor class has no parameters yet, and can produce 2D output
        if not isinstance(module, DataSet):
            return True

        try:
            return int(module.parameters.get("dimensions", 2)) == 2
        except (TypeError, ValueError):
            return False

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        options = {
            "max_text_length": {
                "type": UserInput.OPTION_TEXT,
                "help": "Hover text length",
                "default": 250,
                "min": 20,
                "max": 2000,
                "coerce_type": int,
                "tooltip": "Characters of each item's text to show on hover. Lower this if the result file gets too "
                           "large.",
            },
        }

        if cls.has_clusters(parent_dataset):
            options["colour_clusters"] = {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Colour by cluster",
                "default": True,
                "tooltip": f"Colour items by the cluster found by 'Cluster embeddings'. The {len(CLUSTER_PALETTE)} "
                           f"largest clusters get their own colour; smaller ones share a grey, and items in no "
                           f"cluster are light grey. Hovering an item always shows its cluster.",
            }
        else:
            options["colour_clusters_info"] = {
                "type": UserInput.OPTION_INFO,
                "help": "Run **Cluster embeddings** on the reduced embeddings to colour items by cluster.",
            }

        options.update(cls.get_size_options(cls.get_top_columns(parent_dataset)))

        # allow showing media on the map for media datasets, reusing a sprite
        # sheet extracted earlier rather than decoding the media again here
        sprites = cls.find_sprite_datasets(parent_dataset)
        embeddings = cls.get_embeddings_dataset(parent_dataset)
        if sprites:
            options["thumbnails"] = {
                "type": UserInput.OPTION_CHOICE,
                "help": "Thumbnails",
                "options": {"": "No thumbnails, just dots", **sprites},
                "default": "",
                "tooltip": "Draw each item as its thumbnail instead of a dot using the outputs of 'Generate thumbnails'.",
            }
        elif embeddings and embeddings.type in MEDIA_EMBEDDINGS:
            options["thumbnails_info"] = {
                "type": UserInput.OPTION_INFO,
                "help": "Run **Generate thumbnails** on the media these embeddings came from to show "
                        "thumbnails on the map.",
            }

        return options

    @staticmethod
    def sources_of(dataset):
        """
        Yield the datasets an embedding set was derived from, nearest first.

        :param dataset:  The embeddings dataset
        :return:  Generator of ancestors, nearest first
        """
        try:
            for _ in range(MAX_ANCESTRY):
                dataset = dataset.get_parent() if dataset else None
                if not dataset:
                    return
                yield dataset
        except DataSetException:
            return

    @staticmethod
    def ancestry(dataset):
        """
        Yield a dataset and its ancestors, up to and including the embeddings.

        Bounded, so a broken parent chain (or a stand-in object whose parent is
        always another stand-in) cannot loop forever.

        :param dataset:  The dataset a plot would run on
        :return:  Generator of datasets, nearest first
        """
        try:
            for _ in range(MAX_ANCESTRY):
                if not dataset:
                    return
                yield dataset
                if dataset.type in EMBEDDING_TYPES:
                    return
                dataset = dataset.get_parent()
        except DataSetException:
            return

    @classmethod
    def get_embeddings_dataset(cls, dataset):
        """
        Get the dataset the embeddings were made in.

        Walks up past later steps - a reduction, a clustering - so thumbnails
        and media links are found wherever in the chain a plot runs.

        :param dataset:  The dataset a plot would run on
        :return DataSet|None:  The embeddings, or `None` if there are none
        """
        for ancestor in cls.ancestry(dataset):
            if ancestor.type in EMBEDDING_TYPES:
                return ancestor
        return None

    @classmethod
    def has_clusters(cls, dataset) -> bool:
        """
        Whether the items a plot would run on carry a cluster.

        That is the case when the dataset is, or was made from, clustered
        embeddings.

        :param dataset:  The dataset a plot would run on
        :return bool:  Whether the items carry a cluster
        """
        return any(ancestor.type == CLUSTERED_EMBEDDINGS for ancestor in cls.ancestry(dataset))

    @staticmethod
    def cluster_colours(clusters: list) -> dict:
        """
        Give each point its cluster's colour, and build a legend.

        Colour follows the cluster number, not its size in this plot, so the
        same cluster has the same colour in every plot of one clustering.

        :param list clusters:  Cluster number per point; -1 for noise
        :return dict:  `{palette, colour, legend}`: the fill styles, a palette
          index per point, and `[label, colour]` legend entries
        """
        others = len(CLUSTER_PALETTE)
        noise = others + 1
        palette = [f"{colour}cc" for colour in CLUSTER_PALETTE] + [f"{OTHER_CLUSTERS_COLOUR}b3", f"{NOISE_COLOUR}b3"]

        colour = [noise if cluster < 0 else min(cluster, others) for cluster in clusters]

        sizes = Counter(clusters)
        legend = [[f"Cluster {cluster} ({sizes[cluster]:,})", CLUSTER_PALETTE[cluster]]
                  for cluster in sorted(cluster for cluster in sizes if 0 <= cluster < others)]

        smaller = [cluster for cluster in sizes if cluster >= others]
        if smaller:
            legend.append([f"{len(smaller):,} smaller clusters ({sum(sizes[c] for c in smaller):,})",
                           OTHER_CLUSTERS_COLOUR])
        if sizes.get(-1):
            legend.append([f"No cluster ({sizes[-1]:,})", NOISE_COLOUR])

        return {"palette": palette, "colour": colour, "legend": legend}

    @staticmethod
    def cluster_label(cluster: int) -> str:
        """
        Describe a point's cluster for its hover text.

        :param int cluster:  Cluster number; -1 for noise
        :return str:  Line to add to the hover text
        """
        return "No cluster" if cluster < 0 else f"Cluster {cluster}"

    @staticmethod
    def get_top_columns(dataset) -> list:
        """
        Get the columns of the original dataset, for options that pick one.

        :param dataset:  The dataset a plot would run on
        :return list:  Column names, or an empty list if they cannot be read
        """
        if not dataset:
            return []
        try:
            return dataset.top_parent().get_columns()
        except DataSetException:
            return []

    @staticmethod
    def get_size_options(columns: list) -> dict:
        """
        Options to scale points by a column of the original dataset.

        :param list columns:  Columns of the original dataset
        :return dict:  The options, or none if there are no columns to pick
        """
        if not columns:
            return {}

        return {
            "size_column": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Size by",
                "options": {"": "Nothing (all the same size)", **{column: column for column in columns}},
                "default": "",
                "tooltip": "A column of the original dataset with numbers, such as views or likes, to scale each dot "
                           "or thumbnail by. Values that are not numbers count as the median.",
            },
            "size_scale": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Size scale",
                "options": {"log": "Logarithmic", "linear": "Linear"},
                "default": "log",
                "tooltip": "Counts like views are very skewed: on a linear scale one viral item is huge and nearly "
                           "everything else is the smallest size. A logarithmic scale keeps differences between "
                           "ordinary items visible.",
                "requires": "size_column",
            },
        }

    @classmethod
    def size_factors(cls, raw_values: list, scale: str = "log") -> list | None:
        """
        Turn column values into size factors within `SIZE_RANGE`.

        :param list raw_values:  One value per point; `None` for no value
        :param str scale:  "log" for log(1 + value), "linear" for the values as
          they are. Negative values always use the linear scale.
        :return list|None:  Size factor per point, or `None` if no value is a
          number at all
        """
        numbers = [cls.to_number(value) for value in raw_values]
        parsed = [number for number in numbers if number is not None]
        if not parsed:
            return None

        median = float(np.median(parsed))
        values = np.asarray([median if number is None else number for number in numbers], dtype=np.float64)
        if scale == "log" and values.min() >= 0:
            values = np.log1p(values)

        low, high = values.min(), values.max()
        spread = (values - low) / (high - low) if high > low else np.full(len(values), 0.5)
        return [round(float(SIZE_RANGE[0] + share * (SIZE_RANGE[1] - SIZE_RANGE[0])), 3) for share in spread]

    def get_sizes(self, records: list) -> list | None:
        """
        Get a size factor per record from the 'Size by' column.

        A media file posted more than once takes the largest value among its
        posts, so 'this file once went viral' stays visible.

        :param list records:  Records with `id` and, for media, `post_ids`
        :return list|None:  Size factor per record, or `None` if not sizing
        """
        column = self.parameters.get("size_column")
        if not column:
            return None

        if self.link_posts(records) == len(records):
            self.dataset.log(f"Not sizing by '{column}': no item could be linked to a post in the original dataset.")
            return None

        values = self.read_column(column, {post_id for record in records for post_id in record["post_ids"]})
        largest = []
        for record in records:
            numbers = [self.to_number(values[post_id]) for post_id in record["post_ids"] if post_id in values]
            numbers = [number for number in numbers if number is not None]
            largest.append(max(numbers) if numbers else None)

        sizes = self.size_factors(largest, self.parameters.get("size_scale", "log"))
        if sizes is None:
            self.dataset.log(f"Not sizing by '{column}': it holds no numbers.")
        return sizes

    @staticmethod
    def get_post_ids(record: dict) -> list:
        """
        Get the IDs of the posts an embedding stands for.

        A text embedding's own ID is its post's ID. A media file's ID is a hash
        of the file that matches no post, so media only count their `post_ids`.

        :param dict record:  Embedding record
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

    def link_posts(self, records: list) -> int:
        """
        Set each record's `post_ids` to the posts of the original dataset it
        stands for.

        Media embedded before post IDs were always recorded carry none; the
        archive's metadata still knows which posts a file came from.

        :param list records:  Embedding records; changed in place
        :return int:  How many records could not be linked to any post
        """
        post_id_map = None
        unlinked = 0
        for record in records:
            if "filename" in record and not record.get("post_ids"):
                if post_id_map is None:
                    post_id_map = self.load_media_post_ids()
                record["post_ids"] = post_id_map.get(str(record.get("id")), [])

            record["post_ids"] = self.get_post_ids(record)
            if not record["post_ids"]:
                unlinked += 1

        return unlinked

    def read_columns(self, columns: list, wanted: set) -> dict:
        """
        Read columns of the original dataset for the given posts, in one pass.

        :param list columns:  Columns to read; empty names are skipped
        :param set wanted:  IDs of the posts to read them for
        :return dict:  `{post id: {column: value}}`, leaving out empty values
        """
        columns = [column for column in dict.fromkeys(columns) if column]
        rows = {}
        if not columns or not wanted:
            return rows

        self.dataset.update_status(f"Reading {', '.join(repr(column) for column in columns)} from the original "
                                   f"dataset")
        for item in self.source_dataset.top_parent().iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while reading the original dataset")

            post_id = str(item.get("id"))
            if post_id not in wanted or post_id in rows:
                continue

            rows[post_id] = {column: item.get(column) for column in columns
                             if item.get(column) is not None and str(item.get(column)).strip() != ""}
            if len(rows) == len(wanted):
                break

        return rows

    def read_column(self, column: str, wanted: set) -> dict:
        """
        Read one column of the original dataset for the given posts.

        :param str column:  Column to read
        :param set wanted:  IDs of the posts to read it for
        :return dict:  `{post id: value}` for posts with a non-empty value
        """
        return {post_id: row[column] for post_id, row in self.read_columns([column], wanted).items() if column in row}

    @classmethod
    def build_axis(cls, raw_values: list, spacing: str, column: str = "") -> dict:
        """
        Turn column values into positions between 0 and 1, plus tick labels.

        Values are read as numbers, then as dates, and otherwise as text. A
        column that fails either for even one value is treated as text, which
        still sorts ISO dates correctly.

        :param list raw_values:  One value per point
        :param str spacing:  "rank" to space unique values evenly in sort
          order, "value" to space them proportionally (numbers and dates)
        :param str column:  Column name, used to recognise Unix timestamps
        :return dict:  `{positions, ticks, kind, fallback, keys}`
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
            "keys": keys,
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

    @staticmethod
    def escape(text) -> str:
        """
        Escape text for use in the page's markup, such as the subtitle.

        :param text:  Text, e.g. a user-chosen column name
        :return str:  Text with markup characters escaped
        """
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def media_link_base(self, sprite_dataset=None) -> str | None:
        """
        URL prefix that serves one file out of the media archive.

        4CAT already serves a single member of a dataset's archive, and enforces
        the dataset's own access rules on every request - so putting these links
        in the map grants nothing: an unauthorised viewer following one still
        gets a 403. Nothing about the media is embedded here, only its address.

        Absolute when the instance knows its own hostname, so a downloaded map
        still resolves; root-relative otherwise, which works inside 4CAT itself.

        :return str|None:  Prefix to append a filename to, or `None` when there
          is no archive to link into.
        """
        # the archive is the parent of the embeddings, which are the parent of
        # the reduced embeddings this map is made from
        embeddings = self.get_embeddings_dataset(self.source_dataset)
        # follow the sheet when there is one: its tiles name files in the
        # archive it was made from, which for audio embeddings is the videos
        # rather than the audio pulled out of them
        archive = sprite_dataset.get_parent() if sprite_dataset else None
        if not archive:
            archive = embeddings.get_parent() if embeddings else None
        if not archive:
            return None

        path = f"/download/{archive.key}/?zip_member="
        server_name = self.config.get("flask.server_name")
        if not server_name:
            return path

        protocol = "https://" if self.config.get("flask.https") else "http://"
        return protocol + server_name.rstrip("/") + path

    @classmethod
    def find_sprite_datasets(cls, parent_dataset) -> dict:
        """
        Find sprite sheets made from the same media as these embeddings.

        :param parent_dataset:  The reduced embeddings the map would run on
        :return dict:  `{dataset key: label}`, empty when there are none.
        """
        embeddings = cls.get_embeddings_dataset(parent_dataset)
        if not embeddings or embeddings.type not in MEDIA_EMBEDDINGS:
            return {}

        sprites = {}
        for archive in cls.sources_of(embeddings):
            for sibling in archive.get_children():
                if sibling.type != MediaThumbnails.type or not sibling.is_finished():
                    continue

                size = sibling.parameters.get("thumbnail_size", "?")
                sprites[sibling.key] = f"{size}px, {sibling.num_rows:,} thumbnails"

            if sprites:
                # the nearest ancestor that has any wins: a sheet made from the
                # videos is what an audio embedding should show, and looking
                # further up would only find media these items did not come from
                break

        return sprites

    def process(self):
        """
        Read the reduced embeddings and write the interactive map.
        """
        max_text_length = self.parameters.get("max_text_length", 250)

        records = []
        coordinates = []
        labels = []
        filenames = []
        clusters = []

        self.dataset.update_status("Reading reduced embeddings")
        for item in self.source_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while reading reduced embeddings")

            # the mapped item spreads the coordinates over one column per
            # dimension; the original NDJSON record keeps them as a list
            original = item.original
            point = original.get("coordinates")
            if not point or len(point) != 2:
                continue

            records.append(original)
            coordinates.append(point)
            text = str(original.get("text", "") or "")
            labels.append(text[:max_text_length] + ("…" if len(text) > max_text_length else ""))
            filenames.append(str(original.get("filename", "") or ""))
            clusters.append(original.get("cluster"))

        point_count = len(coordinates)
        if point_count < 3:
            self.dataset.finish_with_error(f"Not enough two-dimensional points to build a map (found {point_count}, "
                                           f"need at least 3).")
            return

        atlas = self.load_sprite(filenames) if any(filenames) else None

        colours = None
        if self.parameters.get("colour_clusters", True) and all(cluster is not None for cluster in clusters):
            colours = self.cluster_colours(clusters)
            labels = [f"{label}\n{self.cluster_label(cluster)}" for label, cluster in zip(labels, clusters)]

        sizes = self.get_sizes(records)

        self.dataset.update_status("Rendering map")
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            outfile.write(self.get_html(np.asarray(coordinates, dtype=np.float64), labels, atlas, colours, sizes))

        self.dataset.update_status(f"Mapped {point_count:,} items", is_final=True)
        self.dataset.finish(point_count)

    def load_sprite(self, filenames: list) -> dict | None:
        """
        Read the chosen sprite sheet and line its tiles up with the points.

        The sheet keys tiles by filename rather than position, so the map is
        free to cap, filter or reorder its own items without the tiles going out
        of step; items the sheet does not cover simply fall back to a dot.

        :param list filenames:  Media filename per point, in point order
        :return dict|None:  `{uri, tile, cols, tiles}` with `tiles[i]` the tile
          index for point `i` (-1 for none), or `None` if unusable.
        """
        key = self.parameters.get("thumbnails")
        if not key:
            return None

        try:
            sprite_dataset = DataSet(key=key, db=self.db, modules=self.modules)
        except DataSetException:
            self.dataset.log("Not drawing thumbnails: the sprite sheet dataset no longer exists.")
            return None

        sprite = MediaThumbnails.read_sprite(sprite_dataset)
        if not sprite:
            self.dataset.log("Not drawing thumbnails: the sprite sheet could not be read.")
            return None

        tiles, sources = self.match_tiles(sprite["tiles"], filenames)
        matched = sum(1 for tile in tiles if tile > -1)
        if not matched:
            self.dataset.log("Not drawing thumbnails: the sprite sheet has no tiles for these items.")
            return None

        self.dataset.log(f"Using {matched:,} of {len(tiles):,} thumbnails from sprite sheet {key}")

        return {
            "uri": sprite["uri"],
            "tile": sprite["tile"],
            "cols": sprite["cols"],
            "tiles": tiles,
            # the names the *sheet* knows, so a click opens the video a frame
            # was taken from rather than the audio extracted out of it. Only
            # files the sheet covers get one, so a click never opens something
            # the map is not showing.
            "files": sources,
            "base": self.media_link_base(sprite_dataset) or "",
        }

    @staticmethod
    def match_tiles(lookup: dict, filenames: list) -> tuple:
        """
        Line a sheet's tiles up with the items being plotted.

        :param dict lookup:  The sheet's `{filename: tile index}`
        :param list filenames:  Item filename per point, in point order
        :return tuple:  `(tile index per point, sheet filename per point)`,
          with -1 and "" where there is no tile.
        """
        by_stem = {}
        for name, tile in lookup.items():
            by_stem.setdefault(name.rsplit(".", 1)[0], (name, tile))

        tiles, sources = [], []
        for filename in filenames:
            if filename in lookup:
                tiles.append(lookup[filename])
                sources.append(filename)
                continue

            name, tile = by_stem.get(filename.rsplit(".", 1)[0], ("", -1))
            tiles.append(tile)
            sources.append(name)

        return tiles, sources

    @staticmethod
    def encode_payload(data: dict, atlas: dict | None = None) -> str:
        """
        Serialise the map's data for embedding in a `<script>` tag.

        Item text is untrusted - it comes from whatever platform the dataset
        was collected from - and this page is injected into 4CAT's own DOM
        unescaped. Escaping the angle brackets and ampersand means no item can
        close the script tag or inject markup, whatever it contains.

        :param dict data:  Points, labels and anything else the page reads
        :param dict atlas:  Sprite sheet from `load_sprite()`, or `None`
        :return str:  JSON, safe to place inside a script tag
        """
        data = dict(data)
        if atlas:
            # base64 is alphanumeric plus + / =, so the escaping below leaves it
            # untouched
            data.update({"atlas": atlas["uri"], "tile": atlas["tile"],
                         "cols": atlas["cols"], "tiles": atlas["tiles"],
                         "files": atlas["files"], "base": atlas["base"]})

        payload = json.dumps(data, ensure_ascii=False)
        return payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    def get_html(self, coordinates, labels, atlas: dict | None = None, colours: dict | None = None,
                 sizes: list | None = None) -> str:
        """
        Build the self-contained HTML page.

        The result is rendered into a 4CAT page with `{{ html|safe }}` as well as
        opened directly when downloaded, so it carries no `<html>`/`<body>`
        wrapper, scopes its CSS to one container, and keeps its JavaScript in an
        IIFE rather than touching globals.

        It does carry a charset declaration: 4CAT's own page declares UTF-8, but
        a downloaded file has nothing to inherit from, and item text is routinely
        non-ASCII. Without it the browser guesses, and guesses latin-1.

        :param coordinates:  2D numpy array of `(x, y)` coordinates
        :param list labels:  Hover text per point, in the same order
        :param dict atlas:  Sprite sheet from `build_atlas()`, or `None` to draw
          plain dots
        :param dict colours:  Cluster colours from `cluster_colours()`, or
          `None` to draw every point alike
        :param list sizes:  Size factor per point from `size_factors()`, or
          `None` to draw every point the same size
        :return str:  HTML
        """
        # normalise to 0-1 so the client only deals with its own viewport
        mins = coordinates.min(axis=0)
        spans = np.where(coordinates.max(axis=0) - mins == 0, 1, coordinates.max(axis=0) - mins)
        normalised = (coordinates - mins) / spans

        points = [[round(float(x), 5), round(float(y), 5)] for x, y in normalised]

        payload = self.encode_payload({"points": points, "labels": labels, "sizes": sizes, **(colours or {})}, atlas)

        container = f"embedding-map-{self.dataset.key}"
        algorithm = self.source_dataset.parameters.get("algorithm", "umap")
        subtitle = f"{len(points):,} items &middot; {algorithm.upper()}"
        if atlas:
            drawn = sum(1 for tile in atlas["tiles"] if tile > -1)
            subtitle += f" &middot; {drawn:,} thumbnails"
        if colours:
            subtitle += " &middot; coloured by cluster"
        if sizes:
            subtitle += " &middot; sized by " + self.escape(self.parameters.get("size_column"))

        interaction = "scroll to zoom, drag to pan"
        if atlas and atlas.get("base"):
            interaction += ", click to open the media"

        return HTML_TEMPLATE % {"container": container, "payload": payload, "subtitle": subtitle,
                                "interaction": interaction}


HTML_TEMPLATE = """<meta charset="utf-8">
<div id="%(container)s" class="embedding-map">
<style>
#%(container)s { position: relative; width: 100%%; height: 80vh; min-height: 420px; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fbfbfc; border: 1px solid #dcdce0; box-sizing: border-box; }
#%(container)s canvas { display: block; width: 100%%; height: 100%%; cursor: grab; }
#%(container)s canvas.dragging { cursor: grabbing; }
#%(container)s canvas.clickable { cursor: pointer; }
#%(container)s .em-bar { position: absolute; top: 0; left: 0; right: 0; display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; font-size: 12px; color: #55555c; background: linear-gradient(#fbfbfcef, #fbfbfc00); pointer-events: none; }
#%(container)s .em-bar button { pointer-events: auto; font: inherit; font-size: 11px; padding: 3px 9px; border: 1px solid #cacad0; border-radius: 3px; background: #fff; color: #33333a; cursor: pointer; }
#%(container)s .em-bar button:hover { background: #f0f0f3; }
#%(container)s .em-tip { position: absolute; max-width: 320px; padding: 8px 10px; font-size: 12px; line-height: 1.45; color: #1c1c20; background: #fff; border: 1px solid #cacad0; border-radius: 4px; box-shadow: 0 2px 10px #00000026; pointer-events: none; opacity: 0; transition: opacity .1s; white-space: pre-wrap; overflow-wrap: anywhere; z-index: 2; }
#%(container)s .em-legend { position: absolute; bottom: 10px; left: 12px; max-height: 45%%; overflow-y: auto; padding: 6px 8px; font-size: 11px; line-height: 1.6; color: #33333a; background: #fbfbfcd9; border-radius: 4px; pointer-events: none; }
#%(container)s .em-key { display: flex; align-items: center; gap: 6px; }
#%(container)s .em-swatch { flex: none; width: 9px; height: 9px; border-radius: 50%%; }
#%(container)s .em-tip.visible { opacity: 1; }
</style>
<div class="em-bar"><span>%(subtitle)s &middot; %(interaction)s</span><button type="button" data-reset>Reset view</button></div>
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
    var points = data.points, labels = data.labels;
    var tiles = data.tiles || null, tileSize = data.tile || 0, atlasCols = data.cols || 1;
    var files = data.files || null, linkBase = data.base || "";
    // a fill per point when coloured by cluster: an index into the palette
    var colour = data.colour || null, palette = data.palette || null;
    // a size factor per point when sized by a column
    var sizes = data.sizes || null;
    function sizeOf(i) { return sizes ? sizes[i] : 1; }

    // the address of the media behind a point, or "" when there is none
    function linkFor(i) {
        if (!files || !linkBase || i < 0 || !files[i]) return "";
        return linkBase + encodeURIComponent(files[i]);
    }
    var atlas = null;
    if (data.atlas) {
        atlas = new Image();
        // one decode for every thumbnail; redraw once it is ready
        atlas.onload = function () { draw(); };
        atlas.src = data.atlas;
    }
    var canvas = root.querySelector("canvas"), ctx = canvas.getContext("2d");
    var tip = root.querySelector(".em-tip");
    var RADIUS = 3.2, PAD = 36;
    var view = {scale: 1, x: 0, y: 0}, width = 0, height = 0, hovered = -1;

    function resize() {
        var dpr = window.devicePixelRatio || 1, box = canvas.getBoundingClientRect();
        width = box.width; height = box.height;
        canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        draw();
    }

    // normalised coordinates -> canvas pixels, with the current pan/zoom applied
    function project(p) {
        return [PAD + p[0] * (width - PAD * 2) * view.scale + view.x,
                PAD + (1 - p[1]) * (height - PAD * 2) * view.scale + view.y];
    }

    // thumbnails grow with zoom up to their stored size; beyond that they would
    // only get blurry, and below ~14px they are unreadable anyway
    function thumbScale() {
        return Math.max(14, Math.min(tileSize, 16 * view.scale));
    }

    // blit one tile out of the sprite sheet, or fall back to a dot for an item
    // whose thumbnail could not be made
    function drawTile(i, xy, drawn) {
        var tile = tiles[i];
        if (tile < 0 || !atlas || !atlas.complete) {
            ctx.beginPath(); ctx.arc(xy[0], xy[1], RADIUS * sizeOf(i), 0, 6.2832); ctx.fill();
            return;
        }
        var sx = (tile %% atlasCols) * tileSize, sy = Math.floor(tile / atlasCols) * tileSize;
        ctx.drawImage(atlas, sx, sy, tileSize, tileSize,
                      xy[0] - drawn / 2, xy[1] - drawn / 2, drawn, drawn);
        // outline the thumbnail in its cluster's colour; items in no cluster
        // (the last palette entry) get none
        if (colour && colour[i] < palette.length - 1) {
            ctx.strokeStyle = palette[colour[i]].slice(0, 7); ctx.lineWidth = 2;
            ctx.strokeRect(xy[0] - drawn / 2, xy[1] - drawn / 2, drawn, drawn);
        }
    }

    function draw() {
        ctx.clearRect(0, 0, width, height);
        ctx.fillStyle = "rgba(40, 92, 168, 0.55)";
        var drawn = tiles ? thumbScale() : 0;
        var margin = tiles ? drawn : 10, fill = -1;

        // two passes when there are thumbnails: dots first, so thumbnails are
        // always drawn on top of them
        for (var pass = tiles ? 0 : 1; pass < 2; pass++) {
            for (var i = 0; i < points.length; i++) {
                if (i === hovered) continue;
                if (tiles && (tiles[i] > -1) !== (pass === 1)) continue;
                var xy = project(points[i]);
                if (xy[0] < -margin || xy[0] > width + margin || xy[1] < -margin || xy[1] > height + margin) continue;
                if (colour && colour[i] !== fill) { fill = colour[i]; ctx.fillStyle = palette[fill]; }
                if (tiles) drawTile(i, xy, drawn * sizeOf(i));
                else { ctx.beginPath(); ctx.arc(xy[0], xy[1], RADIUS * sizeOf(i), 0, 6.2832); ctx.fill(); }
            }
        }

        if (hovered > -1) {
            var h = project(points[hovered]);
            if (tiles) {
                // draw the hovered one last and larger, with an outline, so it
                // is legible even in a dense patch
                var big = Math.min(tileSize * 1.5 * sizeOf(hovered), drawn * 1.8 * sizeOf(hovered));
                drawTile(hovered, h, big);
                ctx.strokeStyle = "#d2451e"; ctx.lineWidth = 2;
                ctx.strokeRect(h[0] - big / 2, h[1] - big / 2, big, big);
            } else {
                ctx.fillStyle = "#d2451e";
                ctx.beginPath(); ctx.arc(h[0], h[1], RADIUS * sizeOf(hovered) + 2.5, 0, 6.2832); ctx.fill();
                ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke();
            }
        }
    }

    function nearest(mx, my) {
        // linear scan: simpler than a spatial index and fast enough at the item
        // counts this processor caps at
        var best = -1, bestDist = 144;
        for (var i = 0; i < points.length; i++) {
            var xy = project(points[i]);
            var d = (xy[0] - mx) * (xy[0] - mx) + (xy[1] - my) * (xy[1] - my);
            if (d < bestDist) { bestDist = d; best = i; }
        }
        return best;
    }

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
            // keep the tooltip inside the container instead of overflowing it
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
        view.x = mx - (mx - view.x) * factor;
        view.y = my - (my - view.y) * factor;
        view.scale = next;
        draw();
    }, {passive: false});

    var drag = {active: false, moved: false, startX: 0, startY: 0, viewX: 0, viewY: 0};
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
        // panning ends in a mouseup too; only a press that stayed put is a click
        if (drag.moved) return;
        var box = canvas.getBoundingClientRect();
        var url = linkFor(nearest(e.clientX - box.left, e.clientY - box.top));
        // noopener: the map is rendered inside 4CAT, and the opened page has no
        // business reaching back into it
        if (url) window.open(url, "_blank", "noopener");
    });

    root.querySelector("[data-reset]").addEventListener("click", function () {
        // drop the hover too: the tooltip describes a point that is about to
        // move, so leaving it up would label the wrong place
        view = {scale: 1, x: 0, y: 0};
        hovered = -1; tip.classList.remove("visible");
        draw();
    });

    if (data.legend && data.legend.length) {
        var legend = root.querySelector(".em-legend");
        data.legend.forEach(function (entry) {
            var key = document.createElement("div"), swatch = document.createElement("span");
            key.className = "em-key"; swatch.className = "em-swatch"; swatch.style.background = entry[1];
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
