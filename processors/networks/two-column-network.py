"""
Generate network of values from two columns
"""
from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput, gdf_escape

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
    description = "Create a Gephi-compatible network comprised of co-occurring values of two columns of the source " \
                  "file. For all items in the dataset, an edge is created between the values of the two columns, if " \
                  "they are not empty. Nodes and edges are weighted by frequency."
    extension = "gdf"

    @classmethod
    def is_compatible_with(cls, dataset=None):
        """
        Allow processor to run on chan datasets

        :param DataSet dataset:  Dataset to determine compatibility with
        """
        return dataset.get_results_path().exists() and dataset.get_results_path().suffix in (".csv", ".ndjson")

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

        nodes = {}
        edges = {}
        edge_separator = "_#_#_#_#_#_"
        processed = 0

        for item in self.iterate_items(self.source_file):
            if column_a not in item or column_b not in item:
                missing = "'" + "' and '".join([c for c in (column_a, column_b) if c not in item]) + "'"
                self.dataset.update_status("Column %s not found in dataset" % missing, is_final=True)
                self.dataset.finish(0)
                return

            processed += 1
            if processed % 100 == 0:
                self.dataset.update_status("Processed %i items (%i nodes found)" % (processed, len(nodes)))

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

            for value_a in values_a:
                for value_b in values_b:
                    # node 'ID', which we use to differentiate by column (or not)
                    node_a = column_a + "-" + value_a if categorise else "node-" + value_a
                    node_b = column_b + "-" + value_b if categorise else "node-" + value_b

                    if not allow_loops and node_a == node_b:
                        continue

                    if node_a not in nodes:
                        nodes[node_a] = 0

                    if node_b not in nodes:
                        nodes[node_b] = 0

                    nodes[node_a] += 1
                    nodes[node_b] += 1

                    edge_nodes = [node_a, node_b]
                    if not directed:
                        # will merge same edges but in different direction
                        edge_nodes = sorted(edge_nodes)
                    edge = edge_separator.join(edge_nodes)

                    if edge not in edges:
                        edges[edge] = 0

                    edges[edge] += 1

        if not edges:
            self.dataset.update_status("No edges could be created for the given parameters", is_final=True)
            self.dataset.finish(0)
            return

        # write GDF file
        directed = "TRUE" if directed else "FALSE"
        self.dataset.update_status("Writing network file")
        with self.dataset.get_results_path().open("w", encoding="utf-8") as results:
            results.write("nodedef>name VARCHAR,label VARCHAR,category VARCHAR,weight INTEGER\n")
            for node, weight in {n: nodes[n] for n in sorted(nodes)}.items():
                results.write("%s,%s,%s,%i\n" % (gdf_escape(node), gdf_escape("-".join(node.split("-")[1:])), gdf_escape(node.split("-")[0]), weight))

            results.write("edgedef>from VARCHAR, to VARCHAR, weight INTEGER,directed BOOLEAN\n")
            for edge, weight in edges.items():
                edge = edge.split(edge_separator)
                results.write("%s,%s,%i,%s\n" % (gdf_escape(edge[0]), gdf_escape(edge[1]), weight, directed))

        self.dataset.finish(len(nodes))
