"""
Find similar words
"""
from nltk.stem.snowball import SnowballStemmer

from backend.lib.preset import ProcessorPreset

from common.lib.helpers import UserInput


class TopHashtags(ProcessorPreset):
    """
    Run processor pipeline to find similar words
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
    def is_compatible_with(cls, module=None, user=None):
        columns = module.get_columns()
        return columns and "hashtags" in module.get_columns()

    def get_processor_pipeline(self):
        """
        This is basically a 'count values' processor with some defaults
        """
        timeframe = self.parameters.get("timeframe")
        top = self.parameters.get("top")

        pipeline = [
            # first, tokenise the posts, excluding all common words
            {
                "type": "attribute-frequencies",
                "parameters": {
                    "columns": ["hashtags"],
                    "split-comma": True,
                    "extract": "none",
                    "timeframe": timeframe,
                    "top": top,
                    "top-style": "per-item",
                    "filter": "",
                    "weigh": "",
                    "to-lowercase": True
                }
            },
        ]

        return pipeline
