"""
Generate co-word network of word collocations
"""

from backend.lib.preset import ProcessorPreset
from backend.lib.processor import ProcessorDescription
from common.lib.compatibility import Compatibility
from common.lib.outputs import Delegated

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class CowordNetworker(ProcessorPreset):
    """
    Generate co-word network
    """
    type = "preset-coword-network"  # job type ID
    description = ProcessorDescription(
        title="Co-word network",
        category="Networks",
        tags=["network"],
        description="Create a network of word co-occurrences. Edges connect words that appear close to each other. Edges and nodes are weighted by how often the words co-occur.",
        icon="circle-nodes",
    )
    extension = "gexf"  # extension of result file, used internally and in UI

    # a preset; its output is its last step's
    output = Delegated()

    # Allow processor to run on collocations
    compatibility = Compatibility(types={"collocations"})

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
