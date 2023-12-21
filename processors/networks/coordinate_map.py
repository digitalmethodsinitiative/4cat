import json

from backend.lib.processor import BasicProcessor


__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

from common.lib.user_input import UserInput


class CoordinateMap(BasicProcessor):
    """
    Wrapper DataSet for a JSON file with plot coordinates that can be used by the cartographer to plot images accordingly
    """
    type = "coordinate-map"  # job type ID
    category = "Networks"  # category
    title = "Coordinate Map"  # title displayed in UI
    description = "Generate via network \"preview\" and export node coordinates"  # description displayed in UI
    extension = "json"  # extension of result file, used internally and in UI

    options= {
        "coordinates": {
            "type": UserInput.OPTION_TEXT_JSON,
            "default": {},
            "help": "JSON containing nodes and their coordinates",
            "tooltip": "e.g. {'node_1': {'x': 0, 'y': 0}, 'node_2': {'x': 1, 'y': 1}}",
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Currently can only be used by the sigma network visualizer; no 4CAT modules have the appropriate input
        """
        # TODO: this needs to be able to run on network datasets, but requires input from sigma preview
        # How do we hide from frontend, but still allow is_compatible_with to return True?
        # return module.get_extension() == "gexf"
        return False # TODO enable this, button in gexf.html when notifications work...

    def process(self):
        """
        This takes a JSON  containing coordinates as input and saves it as a 4CAT Dataset. Designed to be used with
        the sigma network visualizer.
        """
        json_data = self.parameters.get("coordinates")

        with open(self.dataset.get_results_path(), "w") as f:
            f.write(json.dumps(json_data))

        self.dataset.finish(len(json_data))
