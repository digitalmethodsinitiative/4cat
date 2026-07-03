"""
Generate bipartite user-hashtag graph of posts
"""
from backend.lib.preset import ProcessorPreset
from backend.lib.processor import ProcessorDescription
from common.lib.user_input import UserInput
from common.lib.compatibility import Compatibility
from common.lib.outputs import Delegated


__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class HashtagUserBipartiteGrapherPreset(ProcessorPreset):
    """
    Generate bipartite user-hashtag graph of posts
    """
    type = "preset-bipartite-user-tag-network"  # job type ID
    description = ProcessorDescription(
        title="Author-tag network",
        category="Networks",
        tags=["network", "authors", "hashtags"],
        description="Create a bipartite network of authors and the (hash)tags they use, based on co-occurrence. An author and a tag are linked when the author wrote a post with that tag, and the link grows stronger the more often they appear together. Tag nodes are weighted by how often they occur, and author nodes by how many posts they made.",
        icon="circle-nodes",
    )
    extension = "gexf"  # extension of result file, used internally and in UI
    # a preset; its output is its last step's
    output = Delegated()

    # datasets with at least one tag-like column
    compatibility = Compatibility(requires_any_columns={"tags", "hashtags", "groups"})

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        return {
            "to-lowercase": {
                "type": UserInput.OPTION_TOGGLE,
                "default": False,
                "help": "Convert values to lowercase",
                "tooltip": "Merges values with varying cases"
                }
        }

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
