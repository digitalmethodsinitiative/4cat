"""
Generate network of values from two columns
"""
from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, get_interval_descriptor

import networkx as nx
import datetime

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class ColumnNetworker(BasicProcessor):
    """
    Generate network of values from two columns
    """
    type = "column-network"
    category = "Networks"
    title = "Co-column network"
    description = "Create a Gephi-compatible GEXF network comprised of co-occurring values of two columns of the " \
                  "source file. For all items in the dataset, an edge is created between the values of the two " \
                  "columns, if they are not empty. Nodes and edges are weighted by frequency."
    extension = "gexf"

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor to run on all csv and NDJSON datasets

        :param module: Dataset or processor to determine compatibility with
        """

        return module.get_extension() in ("csv", "ndjson")

    options = {
        "column-a": {
            "type": UserInput.OPTION_TEXT,
            "help": "'From' column name",
            "tooltip": "Name of the column of values from which edges originate"
        },
        "column-b": {
            "type": UserInput.OPTION_TEXT,
            "help": "'To' column name",
            "tooltip": "Name of the column of values at which edges terminate"
        },
        "interval": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Make network dynamic by",
            "default": "overall",
            "options": {
                "overall": "Do not make dynamic",
                "year": "Year",
                "month": "Month",
                "week": "Week",
                "day": "Day"
            },
            "tooltip": "Dynamic networks will record, for each node and edge, in which interval(s) they were present. "
                       "Weights will also be calculated per interval. Dynamic graphs can be opened in e.g. Gephi to "
                       "visually analyse the evolution of the network over time."
        },
        "directed": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Directed edges?",
            "default": True,
            "tooltip": "If enabled, an edge from 'hello' in column 1 to 'world' in column 2 creates a different edge "
                       "than from 'world' in column 1 to 'hello' in column 2. If disabled, these would be considered "
                       "the same edge."
        },
        "allow-loops": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Allow loops?",
            "default": False,
            "tooltip": "If enabled, if the two columns contain the same value, a looping edge (from a node to itself) "
                       "is created. If disabled, such edges are ignored."
        },
        "split-comma": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Split column values by comma?",
            "default": False,
            "tooltip": "If enabled, values separated by commas are considered separate nodes, and create separate "
                       "edges. Useful if columns contain e.g. lists of hashtags."
        },
        "categorise": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Categorize nodes by column?",
            "default": True,
            "tooltip": "If enabled, the same values from different columns are treated as separate nodes. For "
                       "example, the value 'hello' from the column 'user' is treated as a different node than the "
                       "value 'hello' from the column 'subject'. If disabled, they would be considered a single node."
        }
    }

    def process(self):
        """
        This takes a 4CAT results file as input, and creates a network file
        based on co-occurring values from two columns of the original data.
        """

        column_a = self.parameters.get("column-a")
        column_b = self.parameters.get("column-b")
        directed = self.parameters.get("directed")
        categorise = self.parameters.get("categorise")
        split_comma = self.parameters.get("split-comma")
        allow_loops = self.parameters.get("allow-loops")
        interval_type = self.parameters.get("interval")

        processed = 0

        network_parameters = {"generated_by": "4CAT Capture & Analysis Toolkit", "source_dataset_id": self.source_dataset.key}
        network = nx.DiGraph(**network_parameters) if directed else nx.Graph(**network_parameters)

        for item in self.iterate_items(self.source_file):
            if column_a not in item or column_b not in item:
                missing = "'" + "' and '".join([c for c in (column_a, column_b) if c not in item]) + "'"
                self.dataset.update_status("Column(s) %s not found in dataset" % missing, is_final=True)
                self.dataset.finish(0)
                return

            processed += 1
            if processed % 500 == 0:
                self.dataset.update_status("Processed %i items (%i nodes found)" % (processed, len(network.nodes)))

            # both columns need to have a value for an edge to be possible
            if not item.get(column_a) or not item.get(column_b):
                continue

            # account for possibility of multiple values by always treating a
            # column as a list of values, just sometimes with only one item
            values_a = [item[column_a].strip()]
            values_b = [item[column_b].strip()]

            if split_comma:
                values_a = [v.strip() for v in values_a.pop().split(",")]
                values_b = [v.strip() for v in values_b.pop().split(",")]

            interval = get_interval_descriptor(item, interval_type)

            for value_a in values_a:
                for value_b in values_b:
                    # node 'ID', which we use to differentiate by column (or not)
                    node_a = column_a + "-" + value_a if categorise else "node-" + value_a
                    node_b = column_b + "-" + value_b if categorise else "node-" + value_b

                    if not allow_loops and node_a == node_b:
                        continue

                    # keep a list of intervals the node occurs in in the node
                    # attributes. Use a dictionary to also record per-interval
                    # frequency
                    if node_a not in network.nodes():
                        network.add_node(node_a, intervals={}, label=value_a, **({"category": column_a} if categorise else {}))

                    if node_b not in network.nodes():
                        network.add_node(node_b, intervals={}, label=value_b, **({"category": column_a} if categorise else {}))

                    if interval not in network.nodes[node_a]["intervals"]:
                        network.nodes[node_a]["intervals"][interval] = 0

                    if interval not in network.nodes[node_b]["intervals"]:
                        network.nodes[node_b]["intervals"][interval] = 0

                    network.nodes[node_a]["intervals"][interval] += 1
                    network.nodes[node_b]["intervals"][interval] += 1

                    # Use the same method to determine per-interval edge weight
                    edge = (node_a, node_b)
                    if edge not in network.edges():
                        network.add_edge(node_a, node_b, intervals={})

                    if interval not in network.edges[edge]["intervals"]:
                        network.edges[edge]["intervals"][interval] = 0

                    network.edges[edge]["intervals"][interval] += 1

        if not network.edges():
            self.dataset.update_status("No edges could be created for the given parameters", is_final=True)
            self.dataset.finish(0)
            return

        # If the network is dynamic, now we calculate spells from the intervals
        # This is a little complicated... but Gephi requires us to define
        # periods of activity rather than just the moment at which a given node
        # or edge was present
        # since gexf can only handle per-day data, generate weights for each
        # day in the interval at the required resolution
        if interval_type not in ("day", "overall"):
            num_items = len(network.nodes) + len(network.edges)
            transformed = 1
            for component in (network.nodes, network.edges):
                for item in component:
                    if transformed % 500 == 0:
                        self.dataset.update_status("Transforming dynamic nodes and edges (%i/%i)" % (transformed, num_items))

                    transformed += 1
                    for interval, weight in component[item]["intervals"].copy().items():
                        del component[item]["intervals"][interval]
                        component[item]["intervals"].update(self.extrapolate_weights(interval, weight, interval_type))

                    component[item]["intervals"] = dict(sorted(component[item]["intervals"].items(), key=lambda item: item[0]))

                    # now figure out the continuous periods of node existence
                    # as well as the period in which each weight was accurate
                    spells = []
                    weights = []
                    start = None
                    weight_start = None
                    previous = None
                    previous_weight = 0
                    for interval, weight in component[item]["intervals"].items():
                        if not start:
                            start = interval
                            weight_start = interval
                            previous = interval
                            previous_weight = weight
                            continue

                        # see if there is a gap of more than one day between
                        # this occurrence and the previous one
                        interval_datetime = datetime.datetime.strptime(interval, "%Y-%m-%d")
                        previous_datetime = datetime.datetime.strptime(previous, "%Y-%m-%d")

                        if interval_datetime > previous_datetime + datetime.timedelta(days=1):
                            # if so, create a new spell
                            spells.append((start, previous))
                            weights.append([weight, weight_start, previous])
                            start = interval
                            weight_start = interval
                        elif weight != previous_weight:
                            # for weights, also do so if the weight changes
                            weights.append([weight, weight_start, previous])
                            weight_start = interval

                        previous = interval
                        previous_weight = weight

                    # add final spells
                    spells.append((start, [*component[item]["intervals"].keys()][-1]))
                    weights.append([previous_weight, weight_start, [*component[item]["intervals"].keys()][-1]])

                    component[item]["spells"] = spells
                    component[item]["frequency"] = weights
                    del component[item]["intervals"]

        self.dataset.update_status("Writing network file")
        
        nx.write_gexf(network, self.dataset.get_results_path())
        self.dataset.finish(len(network.nodes))

    def extrapolate_weights(self, interval, weight, interval_type):
        """
        Expand weight for a given interval into weights per day

        For example, the weight '44' for the interval '2021-32' would return a
        dictionary with seven items, one per day in that week, with all items
        having a YYYY-MM-DD key and 44 as value.

        :param str interval:  Interval descriptor to expand
        :param int weight:  Weight for the given interval
        :param str interval_type:  One of `overall`, `year`, `month`, `week`,
        `day`
        :return dict:  A dictionary containing a weight per day
        """
        if interval_type not in ("month", "week", "year"):
            return {interval: weight}

        if interval_type == "year":
            moment = datetime.datetime(int(interval), 1, 1)
            interval_end = moment + datetime.timedelta(years=1)
        elif interval_type == "month":
            moment = datetime.datetime(int(interval.split("-")[0]), int(interval.split("-")[1]), 1)
            interval_end = moment + datetime.timedelta(months=1)
        elif interval_type == "week":
            # a little bit more complicated
            moment = datetime.datetime.strptime("%s-%s-1" % tuple(interval.split("-")), "%Y-%W-%w").date()
            interval_end = moment + datetime.timedelta(days=7)
        else:
            raise ValueError("extrapolate_weights() expects interval to be one of year, month, week")

        result = {}
        while moment < interval_end:
            result[moment.strftime("%Y-%m-%d")] = weight
            moment += datetime.timedelta(days=1)

        return result
