"""
Generate co-tag network of co-occurring (hash)tags in items
"""

from backend.lib.preset import ProcessorPreset
from common.lib.helpers import UserInput

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
    description = "Create a GEXF network file of tags co-occurring in a posts. " \
                  "Edges are weighted by the amount of tag co-occurrences; nodes " \
                  "are weighted by how often the tag appears in the dataset."  # description displayed in UI
    extension = "gexf"  # extension of result file, used internally and in UI

    options = {
        "to-lowercase": {
            "type": UserInput.OPTION_TOGGLE,
            "default": True,
            "help": "Convert tags to lowercase",
            "tooltip": "Merges tags with varying cases"
        },
        "ignore-tags": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "Tags to ignore",
            "tooltip": "Separate with commas if you want to ignore multiple tags. Do not include the '#' "
                       "character."
        }
    }

    possible_tag_columns = {"tags", "hashtags", "groups"}

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on datasets containing a tags column

        :param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        columns = module.get_columns()
        return bool(set(columns) & cls.possible_tag_columns) if columns else False

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
            columns = self.source_dataset.get_columns()
            tag_column = next((col for col in columns if col in self.possible_tag_columns), None)

        pipeline = [
            {
                "type": "column-network",
                "parameters": {
                    "column-a": tag_column,
                    "column-b": tag_column,
                    "directed": False,
                    "split-comma": True,
                    "categorise": True,
                    "allow-loops": False,
                    "ignore-nodes": self.parameters.get("ignore-tags", ""),
                    "to-lowercase": self.parameters.get("to-lowercase", True)
                }
            }
        ]

        return pipeline
