"""
Describe each cluster by the attributes of the items in it.
"""
import json
import statistics
from collections import Counter
from datetime import datetime, timezone

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.item_mapping import MappedItem, value_or_missing
from common.lib.user_input import UserInput
from processors.machine_learning.cluster_embeddings import ClusterEmbeddings
from processors.machine_learning.embed_media import read_post_id_map

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

# The timestamp format 4CAT's datasources map their items to
TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


class ClusterAttributes(BasicProcessor):
    """
    Summarise attributes from items in a cluster.
    """
    type = "cluster-attributes"  # job type ID
    category = "Metrics"  # category
    title = "Cluster attributes"  # title displayed in UI
    description = ("Describe each embedding cluster by values from the parent dataset as well as other metadata like "
                   "timestamps.")
    extension = "ndjson"  # extension of result file, used internally and in UI

    compatibility = Compatibility(types={"cluster-embeddings"})

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:  Options for this processor
        """
        options = {
            "columns": {
                "type": UserInput.OPTION_TEXT,
                "help": "Columns to describe clusters by",
                "default": "",
                "inline": True,
                "tooltip": "Separate by comma. Any column of the original dataset, e.g. hashtags, author, or a "
                           "column added by another processor.",
            },
            "top_values": {
                "type": UserInput.OPTION_TEXT,
                "help": "Values per column",
                "default": 5,
                "min": 1,
                "max": 50,
                "coerce_type": int,
                "tooltip": "How many of the most common values to list for each column.",
            },
            "split_values": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Count comma-separated values separately",
                "default": True,
                "tooltip": "A column holding a list, such as hashtags, is stored as one comma-separated string. With "
                           "this on, each value is counted on its own rather than the whole combination as one. Turn "
                           "it off for columns where a comma is part of the value itself.",
            },
        }

        top_dataset = parent_dataset.top_parent() if parent_dataset else None
        if top_dataset and top_dataset.get_columns():
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["default"] = []
            options["columns"]["options"] = {column: column for column in top_dataset.get_columns()}

        return options

    def process(self):
        """
        Count the chosen columns' values per cluster.

        Three steps: read the chosen attributes of the original items, work out
        which of those items each cluster holds, then count. The embeddings
        themselves are never read, so this costs no more than reading the file.
        """
        columns = self.parameters.get("columns") or []
        if isinstance(columns, str):
            columns = [column.strip() for column in columns.split(",") if column.strip()]
        if not columns:
            self.dataset.finish_with_error("Choose at least one column to describe the clusters by.")
            return

        genealogy = self.source_dataset.get_genealogy()
        top_dataset = genealogy[0]
        if top_dataset.key == self.source_dataset.key:
            self.dataset.finish_with_error("These clusters have no original dataset to take attributes from.")
            return

        attributes = self.read_attributes(top_dataset, columns)
        if not attributes:
            self.dataset.finish_with_error(f"None of the chosen columns could be read from "
                                           f"'{top_dataset.get_label()}'.")
            return

        members, measures, unmatched = self.collect_members(genealogy)
        if not members:
            self.dataset.finish_with_error("The clustered items could not be matched to the original dataset, so "
                                           "there are no attributes to describe them by.")
            return

        if unmatched:
            self.dataset.log(f"{unmatched:,} clustered items could not be matched to an item in "
                             f"'{top_dataset.get_label()}' and are left out of the attribute counts.")

        total_items = sum(measure["items"] for measure in measures.values())
        everything = set().union(*members.values())

        self.dataset.update_status("Describing clusters")
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            outfile.write(json.dumps(self.describe("all", everything, attributes, columns,
                                                   items=total_items, share=1.0),
                                     ensure_ascii=False) + "\n")

            for cluster in sorted(members):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while describing clusters")

                measure = measures[cluster]
                record = self.describe(cluster, members[cluster], attributes, columns,
                                       items=measure["items"],
                                       share=measure["items"] / total_items if total_items else 0)

                # carried from the clustering, where they were measured on the
                # vectors themselves
                if measure["concentration"] is not None:
                    record["concentration"] = measure["concentration"]
                if measure["memberships"]:
                    record["membership_median"] = round(statistics.median(measure["memberships"]), 4)

                outfile.write(json.dumps(record, ensure_ascii=False) + "\n")

        self.dataset.update_status(f"Described {len(members):,} clusters by {len(columns)} column"
                                   f"{'s' if len(columns) > 1 else ''}", is_final=True)
        self.dataset.finish(len(members) + 1)

    def read_attributes(self, top_dataset, columns: list) -> dict:
        """
        Read the chosen columns + timestamp for every original item.

        :param top_dataset:  Dataset the embeddings were made from
        :param list columns:  Columns to keep
        :return dict:  `{item ID: {column: value}}`, with the timestamp under
          `timestamp` when the dataset has one
        """
        self.dataset.update_status(f"Reading {', '.join(columns)} from the original dataset")
        attributes = {}
        missing_columns = set(columns)

        for item in top_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while reading the original dataset")

            kept = {column: item.get(column) for column in columns if item.get(column) is not None}
            missing_columns -= set(kept)
            if item.get("timestamp"):
                kept["timestamp"] = item["timestamp"]

            attributes[str(item.get("id"))] = kept

        if missing_columns:
            self.dataset.log(f"No values found for: {', '.join(sorted(missing_columns))}")

        return attributes

    def collect_members(self, genealogy: list) -> tuple:
        """
        Work out which original items each cluster holds.

        An embedding stands for one or more items of the original dataset: a
        text embedding for its own post, a media embedding for every post the
        file appeared in.

        :param list genealogy:  This dataset's ancestry, oldest first
        :return tuple:  `(members, measures, unmatched)` - the item IDs per
          cluster, what the clustering already measured per cluster, and how
          many embeddings matched no item
        """
        self.dataset.update_status("Matching clustered items to the original dataset")
        members, measures, unmatched = {}, {}, 0
        post_id_map = None

        for item in self.source_dataset.iterate_items(self, get_annotations=False):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while reading clusters")

            record = item.original
            if "cluster" not in record:
                continue

            cluster = int(record["cluster"])
            post_ids = ClusterEmbeddings.get_post_ids(record)
            if post_ids is None:
                if post_id_map is None:
                    post_id_map = read_post_id_map(self.archive_path(genealogy), log=self.dataset.log)
                post_ids = post_id_map.get(str(record.get("id")), [])

            measure = measures.setdefault(cluster, {"items": 0, "concentration": None, "memberships": []})
            measure["items"] += 1
            if record.get("cluster_concentration") is not None:
                measure["concentration"] = record["cluster_concentration"]
            if record.get("cluster_probability") is not None:
                measure["memberships"].append(float(record["cluster_probability"]))

            if not post_ids:
                unmatched += 1
                continue

            members.setdefault(cluster, set()).update(str(post_id) for post_id in post_ids)

        return members, measures, unmatched

    @staticmethod
    def archive_path(genealogy: list):
        """
        The media archive among this dataset's ancestors, if there is one.

        Media embeddings made before post IDs were recorded in the embedding
        itself need the archive's `.metadata.json` to be matched to posts.

        :param list genealogy:  Dataset ancestry, oldest first
        :return Path|None:  Path to the archive
        """
        for dataset in reversed(genealogy):
            path = dataset.get_results_path()
            if path.suffix.lower() == ".zip":
                return path

        return None

    def describe(self, cluster, item_ids: set, attributes: dict, columns: list,
                 items: int, share: float) -> dict:
        """
        Build one cluster's record.

        :param cluster:  Cluster number, or `"all"` for the whole dataset
        :param set item_ids:  IDs of the original items in this cluster
        :param dict attributes:  Attributes per item ID
        :param list columns:  Columns to count
        :param int items:  Embeddings in this cluster
        :param float share:  This cluster's share of all embeddings
        :return dict:  The cluster's record
        """
        # sorted, so that values tying on count always come out in the same
        # order and the same input gives the same table twice
        known = [attributes[item_id] for item_id in sorted(item_ids) if item_id in attributes]
        record = {
            "cluster": cluster,
            "items": items,
            "posts": len(known),
            "share": round(share, 4),
            "top_values": {column: self.top_values(known, column) for column in columns},
        }
        record.update(self.timespan(known))

        return record

    def top_values(self, known: list, column: str) -> list:
        """
        The most common values of one column among a cluster's items.

        :param list known:  Attributes of each item in the cluster
        :param str column:  Column to count
        :return list:  `[{"value", "items", "share"}, ...]`, most common first
        """
        counts = Counter()
        for item in known:
            value = item.get(column)
            if value is None or value == "":
                continue

            if self.parameters.get("split_values", True) and isinstance(value, str) and "," in value:
                counts.update(part.strip() for part in value.split(",") if part.strip())
            elif isinstance(value, (list, tuple, set)):
                counts.update(str(part) for part in value)
            else:
                counts[str(value)] += 1

        # the share is of the items in the cluster, not of the counted values:
        # a list column can have several values per item, so shares can add up
        # to more than 1
        return [{"value": value, "items": count, "share": round(count / len(known), 4) if known else 0}
                for value, count in counts.most_common(self.parameters.get("top_values", 5))]

    def timespan(self, known: list) -> dict:
        """
        When the items in a cluster are from.

        :param list known:  Attributes of each item in the cluster
        :return dict:  Timestamp fields, or empty when none could be read
        """
        moments = []
        for item in known:
            moment = self.read_timestamp(item.get("timestamp"))
            if moment is not None:
                moments.append(moment)

        if not moments:
            return {}

        moments.sort()

        return {
            "timestamp_start": self.format_timestamp(moments[0]),
            "timestamp_end": self.format_timestamp(moments[-1]),
            "timestamp_median": self.format_timestamp(statistics.median(moments)),
            "timestamp_mean": self.format_timestamp(statistics.mean(moments)),
        }

    @staticmethod
    def read_timestamp(value) -> float | None:
        """
        Read a timestamp as seconds since the epoch.

        :param value:  A `YYYY-MM-DD HH:MM:SS` string, or seconds already
        :return float|None:  Seconds since the epoch, or `None` if unreadable
        """
        if value is None or value == "":
            return None

        if isinstance(value, (int, float)):
            return float(value)

        try:
            return datetime.strptime(str(value), TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            return None

    @staticmethod
    def format_timestamp(moment: float) -> str:
        """
        Write seconds since the epoch the way datasources write timestamps.

        :param float moment:  Seconds since the epoch
        :return str:  `YYYY-MM-DD HH:MM:SS`
        """
        return datetime.fromtimestamp(moment, tz=timezone.utc).strftime(TIMESTAMP_FORMAT)

    @staticmethod
    def map_item(item):
        """
        Flatten a cluster's record into a row.

        The counted values become one readable cell per column, named after the
        column with a `top_` prefix so they cannot collide with the measures.

        :param item:  Item to map
        :return MappedItem:  Flat row
        """
        row = {
            "cluster": item.get("cluster"),
            "items": item.get("items"),
            "posts": item.get("posts"),
            "share": item.get("share"),
            # only there when the clustering measured them: k-means scores no
            # membership, and the baseline row is not one cluster
            "concentration": value_or_missing(item, "concentration", -1),
            "membership_median": value_or_missing(item, "membership_median", -1),
            "timestamp_start": value_or_missing(item, "timestamp_start", ""),
            "timestamp_end": value_or_missing(item, "timestamp_end", ""),
            "timestamp_median": value_or_missing(item, "timestamp_median", ""),
            "timestamp_mean": value_or_missing(item, "timestamp_mean", ""),
        }

        for column, values in (item.get("top_values") or {}).items():
            row[f"top_{column}"] = ", ".join(f"{value['value']} ({value['share'] * 100:.0f}%)"
                                             for value in values)

        return MappedItem(row)
