"""
Generate co-word network of word collocations
"""

from backend.lib.preset import ProcessorPreset

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class CowordNetworker(ProcessorPreset):
    """
    Generate co-word network
    """
    type = "preset-coword-network"  # job type ID
    category = "Networks"  # category
    title = "Co-word network"  # title displayed in UI
    description = "Create a GEXF network file of word co-occurences. Edges denote " \
                  "words that appear close to each other. Edges and nodes are weighted by the " \
                  "amount of co-word occurrences."  # description displayed in UI
    extension = "gexf"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor to run on collocations

        :param module: Module to determine compatibility with
        """
        return module.type == "collocations"

    def get_processor_pipeline(self):
        """
        Generate co-word network

        This is essentially a network between the 'word_1' column and the
        'word_2' columns of the dataset, and as such, this is a preset with
        pre-defined settings for the 'two columns network' processor.
        """

        pipeline = [
            {
                "type": "column-network",
                "parameters": {
                    "column-a": "word_1",
                    "column-b": "word_2",
                    "directed": False,
                    "split-comma": False,
                    "categorise": False,
                    "allow-loops": True
                }
            }
        ]

        return pipeline
