"""
Generate bipartite user-hashtag graph of posts
"""
import csv

from backend.abstract.preset import ProcessorPreset

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
    def is_compatible_with(cls, module=None):
        """
        Allow processor on datasets containing a tags column

        :param module: Dataset or processor to determine compatibility with
        """
        if module.type == "twitterv2-search":
            # ndjson, difficult to sniff
            return True
        elif module.is_dataset():
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
                    "allow-loops": False
                }
            }
        ]

        return pipeline
