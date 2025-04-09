"""
Find most-used hashtags in a dataset
"""
from backend.lib.preset import ProcessorPreset
from common.lib.helpers import UserInput
from processors.networks.cotag_network import CoTaggerPreset


class TopHashtags(ProcessorPreset):
    """
    Run processor pipeline to find top hashtags
    """
    type = "preset-top-hashtags"  # job type ID
    category = "Combined processors"  # category. 'Combined processors' are always listed first in the UI.
    title = "Find top hashtags"  # title displayed in UI
    description = "Count how often each hashtag occurs in the dataset and sort by this value"
    extension = "csv"

    options = ({
        "timeframe": {
            "type": UserInput.OPTION_CHOICE,
            "default": "all",
            "options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day"},
            "help": "Find top hashtags per"
        },
        "top": {
            "type": UserInput.OPTION_TEXT,
            "default": 0,
            "help": "Include this many top hashtags",
            "tooltip": "For no limit, use '0'",
            "coerce_type": int,
        },
    })

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Check if dataset has a hashtag attribute

        :param module:  Dataset to check
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return bool:
        """
        columns = module.get_columns()
        return columns and any([tag in columns for tag in CoTaggerPreset.possible_tag_columns])	

    def get_processor_pipeline(self):
        """
        This is basically a 'count values' processor with some defaults
        """
        timeframe = self.parameters.get("timeframe")
        top = self.parameters.get("top")
        columns = self.source_dataset.get_columns()
        tag_column = next((col for col in columns if col in CoTaggerPreset.possible_tag_columns), None)

        pipeline = [
            {
                "type": "attribute-frequencies",
                "parameters": {
                    "columns": [tag_column],
                    "split-comma": True,
                    "extract": "none",  # *not* 'hashtags', because they may not start with #
                    "timeframe": timeframe,
                    "top": top,
                    "top-style": "per-item",
                    "filter": "",
                    "weigh": "",
                    "to-lowercase": True,
                    "count_missing": False
                }
            },
        ]

        return pipeline
