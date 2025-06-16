"""
Convert a GEXF network file to a CSV file
"""
from backend.lib.processor import BasicProcessor

import networkx as nx
import csv
import heapq

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class GexfToCsv(BasicProcessor):
    """
    Convert a GEXF network file to a CSV file
    """
    type = "gexf-to-csv"
    category = "Networks"
    title = "Export Network as CSV Spreadsheet"
    description = "Convert a GEXF network file to a CSV spreadsheet"
    extension = "csv"

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor to run on all csv and NDJSON datasets

        :param module: Module to determine compatibility with
        """
        return module.get_extension() in ["gexf"]

    def process(self):
        """
        This takes a GEXF file and converts it to a CSV file
        """
        self.dataset.update_status("Reading network file")
        graph = nx.read_gexf(self.source_dataset.get_results_path())
        # Use a generator to lazily sort edges by weight (frequency may be intervals; weight is overall edge frequency per 4CAT)
        sorted_edges = heapq.nlargest(
            len(graph.edges),  # Number of edges to process
            graph.edges(data=True),
            key=lambda edge: edge[2].get("weight", 0)  # Sort by edge weight
        )

        self.dataset.update_status("Writing CSV file")
        with self.dataset.get_results_path().open("w", newline="") as output:
            writer = False
            lines = 0
            for source, target, edge_attributes in sorted_edges:
                source_attributes = graph.nodes[source]
                target_attributes = graph.nodes[target]

                result = {"source": source}
                result.update({f"source_{k}": v for k,v in source_attributes.items()})
                result.update({"target": target})
                result.update({f"target_{k}": v for k,v in target_attributes.items()})
                result.update({f"edge_{attr_key}": edge_attributes[attr_key] for attr_key in sorted(edge_attributes, key=lambda k: k == "id", reverse=True)})
        
                if writer is False:
                    # Write header
                    # Notes: this assumes that all nodes have the same attributes which ought to be True for GEXF files written by 4CAT
                    writer = csv.DictWriter(output, fieldnames=result.keys())
                    writer.writeheader()  
                writer.writerow(result)
                lines += 1
                if lines % 1000 == 0:
                    self.dataset.update_status(f"Writing CSV file: {lines} lines written")
                    self.dataset.update_progress(lines / len(graph.edges))
        self.dataset.update_status("Finished.")
        self.dataset.finish(num_rows=lines)