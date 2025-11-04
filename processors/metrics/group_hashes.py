import csv
import json
import imagehash

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException
from common.lib.helpers import UserInput, normalize_crhash_components

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

class HashGrouper(BasicProcessor):
    """
    Group hashes
    """
    type = "image-hash-grouper"  # job type ID
    category = "Conversion"  # category
    title = "Group similar hashes"  # title displayed in UI
    description = "Calculate groups of similar hashes from a CSV file."  # description displayed in UI
    extension = "csv"

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on. Can be used, in conjunction with
            config, to show some options only to privileged users.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        return {
            "similarity-threshold": {
                "type": UserInput.OPTION_TEXT,
                "help": "Similarity threshold (percent)",
                "coerce_type": int,
                "default": 5,
                "min": 0,
                "max": 100,
                "tooltip": "Maximum difference as a percentage of hash bits (0–100)."
            }
        }

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on above hasher output

        Could also allow on any CSV with appropriate fields

        :param module: Module to determine compatibility with
        """
        return module.type == "image-hasher"
    
    @staticmethod
    def compute_groups(hashes, hash_type: str, hash_size: int | None, similarity_pct: float) -> list[int]:
        """
        Group a list of hash objects into connected components using a percent-based
        threshold. Returns a list of group labels (0..k-1) aligned with `hashes`.

        - For phash/whash: Hamming distance between ImageHash objects; allowed bits
          computed once from hash_size^2 and similarity_pct.
        - For crhash: Each item may be either an object with `.hashes` or a list of
          component ImageHash objects. Distance is the minimum pairwise Hamming distance
          between components. Allowed bits per pair uses the smaller component bit-length.
        """
        n = len(hashes)
        if n == 0:
            return []

        # Prebind distance and allowed bits based on type
        if hash_type in ("phash", "whash-haar", "whash-db4"):
            if hash_size is None:
                raise ValueError("hash_size required for fixed-length hashes")
            total_bits = int(hash_size) * int(hash_size)
            allowed_const = int((similarity_pct / 100.0) * total_bits)

            def distance_fn(i: int, j: int) -> int:
                return hashes[i] - hashes[j]

            def allowed_bits(i: int, j: int) -> int:
                return allowed_const

        elif hash_type == "crhash":
            # Normalize to lists of components and precompute component bit lengths
            comps = []  # list[list[ImageHash]]
            comp_bits = []
            for idx, h in enumerate(hashes):
                try:
                    c = normalize_crhash_components(h)
                except Exception as e:
                    raise ValueError(f"Malformed crop-resistant hash at index {idx}: {e}")
                try:
                    bits0 = c[0].hash.size
                except Exception as e:
                    raise ValueError(f"Invalid crop-resistant component at index {idx}: {e}")
                comps.append(c)
                comp_bits.append(bits0)

            def distance_fn(i: int, j: int) -> int:
                best = None
                for a in comps[i]:
                    for b in comps[j]:
                        d = a - b
                        if best is None or d < best:
                            best = d
                            if best == 0:
                                return 0
                return best  # type: ignore[return-value]

            def allowed_bits(i: int, j: int) -> int:
                bits = comp_bits[i] if comp_bits[i] <= comp_bits[j] else comp_bits[j]
                return int((similarity_pct / 100.0) * bits)

        else:
            raise ValueError(f"Unknown hash type for grouping: {hash_type}")

        # Connected-components labeling
        visited = [False] * n
        labels = [-1] * n
        gid = 0
        for seed in range(n):
            if visited[seed]:
                continue
            stack = [seed]
            visited[seed] = True
            labels[seed] = gid
            while stack:
                u = stack.pop()
                for v in range(n):
                    if visited[v]:
                        continue
                    d = distance_fn(u, v)
                    if d <= allowed_bits(u, v):
                        visited[v] = True
                        labels[v] = gid
                        stack.append(v)
            gid += 1
        return labels

    def process(self):
        """
        Read image hashes from a CSV (output of ImageHasher) and recompute groups
        using a new similarity threshold percentage. Writes a new CSV with an
        updated 'group' column and preserves other fields.
        """
        similarity_pct = float(self.parameters.get("similarity-threshold", 5))

        # Read rows and reconstruct hash objects
        rows = []
        hashes = []  # parallel to rows
        hash_type = None
        hash_size = None

        for item in self.source_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while grouping hashes")
            
            row = dict(item)
            # Discover and enforce a single hash_type
            row_hash_type = row.get("hash_type")
            if hash_type is None:
                hash_type = row_hash_type
            elif row_hash_type != hash_type:
                raise ValueError(f"Mixed hash types in input: {row_hash_type} vs {hash_type}")

            # Capture hash_size for fixed-length hashes (phash/whash)
            if hash_type in ("phash", "whash-haar", "whash-db4") and hash_size is None:
                try:
                    hs = row.get("hash_size")
                    hash_size = int(hs) if hs is not None else None
                except Exception:
                    hash_size = None

            # Parse image_hash into objects
            hash_str = row.get("image_hash")
            if hash_str is None:
                raise ValueError("Missing image_hash column in input")

            if hash_type in ("phash", "whash-haar", "whash-db4"):
                hash_obj = imagehash.hex_to_hash(hash_str)
            elif hash_type == "crhash":
                comps = json.loads(hash_str)
                if not isinstance(comps, list) or not comps:
                    raise ValueError("Empty or malformed crop-resistant components")
                hash_obj = [imagehash.hex_to_hash(h) for h in comps]
            else:
                raise ValueError(f"Unsupported hash_type in grouper: {hash_type}")

            rows.append(row)
            hashes.append(hash_obj)

        num_images = len(rows)

        # Prepare fieldnames: ensure 'group' first
        base_fields = list(rows[0].keys()) if rows else ["filename", "image_hash", "hash_type", "hash_size"]
        if "group" in base_fields:
            base_fields.remove("group")
        fieldnames = ["group"] + base_fields

        # Compute groups using shared helper
        labels = HashGrouper.compute_groups(hashes, hash_type, hash_size, similarity_pct)
        group_count = max(labels) + 1 if labels else 0

        # Write output CSV with new groups
        with self.dataset.get_results_path().open("w", newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            for i, row in enumerate(rows):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while writing hash groups")

                # Ensure our freshly computed label takes precedence over any existing 'group' in the input row
                out = {**row, "group": labels[i]}
                writer.writerow(out)

        self.dataset.update_status(
            f"Grouped {num_images:,} items into {group_count:,} groups (threshold={similarity_pct:.2f}%)",
            is_final=True,
        )
        self.dataset.finish(num_rows=num_images)
