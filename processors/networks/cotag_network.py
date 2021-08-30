"""
Generate co-tag network of co-occurring (hash)tags in items
"""
import csv

from backend.abstract.preset import ProcessorPreset

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class CoTaggerPreset(ProcessorPreset):
    """
    Generate co-tag network of co-occurring (hash)tags in items
    """
    type = "preset-cotag-network"  # job type ID
    category = "Networks"  # category
    title = "Co-tag network"  # title displayed in UI
    description = "Create a Gephi-compatible network comprised of all tags appearing in the dataset, with edges " \
                  "between all tags used together on an item. Edges are weighted by the amount of co-tag " \
                  "occurrences; nodes are weighted by the frequency of the tag."  # description displayed in UI
    extension = "gexf"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on datasets containing a tags column

        :param module: Dataset or processor to determine compatibility with
        """
        if module.type == "twitterv2-search":
            # ndjson, difficult to sniff
            return True
        if module.is_dataset():
            if module.get_extension() == "csv":
                # csv can just be sniffed for the presence of a column
                with module.get_results_path().open(encoding="utf-8") as infile:
                    reader = csv.DictReader(infile)
                    try:
                        return bool(set(reader.fieldnames) & {"tags", "hashtags", "groups"})
                    except (TypeError, ValueError):
                        return False
        else:
            return False

    def get_processor_pipeline(self):
        """
        Generate co-tag graph of items

        This is essentially a network between non-equal values of two copies of
        an item's tag column, and as such, this is a preset with pre-defined
        settings for the 'two columns network' processor.
        """

        if self.source_dataset.parameters.get("datasource") == "usenet":
            # groups are not really hashtags, but for the purposes of this
            # network, they are essentially the same
            tag_column = "groups"
        elif self.source_dataset.parameters.get("datasource") == "tumblr":
            # same for tumblr's tags
            tag_column = "tags"
        else:
            tag_column = "hashtags"

        pipeline = [
            {
                "type": "column-network",
                "parameters": {
                    "column-a": tag_column,
                    "column-b": tag_column,
                    "directed": False,
                    "split-comma": True,
                    "categorise": True,
                    "allow-loops": False
                }
            }
        ]

        return pipeline
