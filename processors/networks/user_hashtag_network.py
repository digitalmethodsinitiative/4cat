"""
Generate bipartite user-hashtag graph of posts
"""
from backend.lib.preset import ProcessorPreset
from common.lib.user_input import UserInput


__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class HashtagUserBipartiteGrapherPreset(ProcessorPreset):
    """
    Generate bipartite user-hashtag graph of posts
    """
    type = "preset-bipartite-user-tag-network"  # job type ID
    category = "Networks"  # category
    title = "Bipartite Author-tag Network"  # title displayed in UI
    description = "Produces a bipartite graph based on co-occurence of (hash)tags and people. If someone wrote a post with a certain tag, there will be a link between that person and the tag. The more often they appear together, the stronger the link. Tag nodes are weighed on how often they occur. User nodes are weighed on how many posts they've made."  # description displayed in UI
    extension = "gexf"  # extension of result file, used internally and in UI

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        return {
            "to-lowercase": {
                "type": UserInput.OPTION_TOGGLE,
                "default": False,
                "help": "Convert values to lowercase",
                "tooltip": "Merges values with varying cases"
                }
        }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on datasets containing a tags column

        :param module: Module to determine compatibility with
        """
        usable_columns = {"tags", "hashtags", "groups"}
        columns = module.get_columns()
        return bool(set(columns) & usable_columns) if columns else False

    def get_processor_pipeline(self):
        """
        Generate bipartite user-hashtag graph of items

        This is essentially a network between the 'author' column and the
        values in the tag column of the dataset, and as such, this is a preset
        with pre-defined settings for the 'two columns network' processor.
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
                    "column-a": "author",
                    "column-b": tag_column,
                    "directed": False,
                    "split-comma": True,
                    "categorise": True,
                    "allow-loops": False,
                    "to-lowercase": self.parameters.get("to-lowercase", False),
                }
            }
        ]

        return pipeline
