"""
Walk from one embedding to its nearest neighbour, and on, to order items by similarity and get a
'latent space path' that users can navigate.
"""
import csv
import secrets

import numpy as np

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.embeddings import STATUS_EVERY, get_vector, normalise_in_place
from common.lib.exceptions import ProcessorInterruptedException, QueryParametersException
from common.lib.user_input import UserInput
from processors.machine_learning.embed_media import read_post_id_map

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

# Embeddings with a cluster per item
CLUSTERED_EMBEDDINGS = "cluster-embeddings"

# Embeddings are compared with the start in chunks of this many while reading
READ_CHUNK = 2000

# Most items a path can visit--else we'll run into memory errors
MAX_NEIGHBOURHOOD = 50000


class LatentSpacePath(BasicProcessor):
	"""
	Order embeddings as a path through latent space.

	Takes a starting embedding and its nearest neighbours, then walks from the
	start to its nearest neighbour, from there to the nearest neighbour not yet
	visited, and so on until every neighbour is visited.
	"""
	type = "latent-space-path"  # job type ID
	category = "Machine learning"  # category
	title = "Latent space path"  # title displayed in UI
	description = ("Generate a sequence on the basis of neighboring embeddings. Start with one embedding, "
				   "then get the nearest neighbor, then get its nearest neighbor that was not the previous embedding, and "
				   "so forth.")
	extension = "csv"  # extension of result file, used internally and in UI

	compatibility = Compatibility(types={"text-embeddings", "video-embeddings", "image-embeddings",
										 CLUSTERED_EMBEDDINGS})

	# Annotations are saved in batches of this many while writing
	annotation_batch_size = 1000

	references = [
		"[Nearest neighbour algorithm (greedy path)](https://en.wikipedia.org/wiki/Nearest_neighbour_algorithm)",
		"[Cosine similarity](https://en.wikipedia.org/wiki/Cosine_similarity)",
	]

	@classmethod
	def get_options(cls, parent_dataset=None, config=None) -> dict:
		"""
		Get processor options

		:param parent_dataset DataSet:  An object representing the dataset that
			the processor would be or was run on.
		:param config ConfigManager|None config:  Configuration reader (context-aware)
		:return dict:   Options for this processor
		"""
		starts = {
			"random": "A random embedding",
			"embedding": "A specific embedding (by embedding ID)",
			"post": "A specific post (by post ID)",
		}
		clustered = parent_dataset is not None and getattr(parent_dataset, "type", None) == CLUSTERED_EMBEDDINGS
		if clustered:
			starts["cluster"] = "The centre of a cluster"

		options = {
			"path_info": {
				"type": UserInput.OPTION_INFO,
				"help": "The path starts at one embedding and its nearest neighbours. From the start it steps to the "
						"most similar neighbour, then to the most similar neighbour not yet visited, and so on. "
						"Note that the path at some point will 'drift' since once the closest neighbours are visited, "
						"it needs to jump further. Step distance in the results shows where that happens.",
			},
			"start": {
				"type": UserInput.OPTION_CHOICE,
				"help": "Start at",
				"options": starts,
				"default": "random",
			},
			"start_embedding": {
				"type": UserInput.OPTION_TEXT,
				"help": "Embedding ID",
				"default": "",
				"tooltip": "The `id` of an embedding in the parent dataset. For text, this is the post ID; for media, "
						   "it is the file's name without extension.",
				"requires": "start==embedding",
			},
			"start_post": {
				"type": UserInput.OPTION_TEXT,
				"help": "Post ID",
				"default": "",
				"tooltip": "The ID of a post in the original dataset. The path starts at the first embedding made "
						   "for that post.",
				"requires": "start==post",
			},
			"neighbours": {
				"type": UserInput.OPTION_TEXT,
				"help": "Path length (nearest neighbours)",
				"default": 1000,
				"min": 2,
				"max": MAX_NEIGHBOURHOOD,
				"coerce_type": int,
				"tooltip": f"The path visits the start and its nearest neighbours, up to this many items in total "
						   f"(max {MAX_NEIGHBOURHOOD:,}). Time grows quickly with this number: tens of thousands "
						   f"of items can take several minutes.",
			},
			"save_annotations": {
				"type": UserInput.OPTION_ANNOTATION,
				# the written labels fold in the starting point, which is not
				# known until the run; this is the readable stem of them
				"label": "latent path position and distance",
				"default": False,
				"tooltip": "Add each item's position on the path and its distance to the previous item as "
						   "annotations to the top dataset. Sort by position in the Explorer to browse the path. "
						   "Items not on the path get no annotation.",
			},
		}

		if clustered:
			options["start_cluster"] = {
				"type": UserInput.OPTION_TEXT,
				"help": "Cluster number",
				"default": 0,
				"min": 0,
				"coerce_type": int,
				"tooltip": "The path starts at the embedding closest to the average of this cluster's embeddings, "
						   "and its neighbours are the embeddings closest to that average.",
				"requires": "start==cluster",
			}

		return options

	@classmethod
	def validate_query(cls, query, request, config):
		"""
		Validate input

		:param dict query:  Query parameters, as submitted by the user via the web interface
		:param request:  Flask request
		:param ConfigManager config:  Configuration reader
		:return dict:  Validated query parameters
		"""
		start = query.get("start", "random")
		if start == "embedding" and not str(query.get("start_embedding", "")).strip():
			raise QueryParametersException("Enter the ID of the embedding to start at.")
		if start == "post" and not str(query.get("start_post", "")).strip():
			raise QueryParametersException("Enter the ID of the post to start at.")

		return query

	def process(self):
		"""
		Find the start, gather its nearest neighbours, walk them, write the path.

		Only the neighbourhood is held in memory. The parent is read once to
		find the start (twice for a random start) and once more to keep the
		closest embeddings to it, so the size of the parent does not matter.
		"""
		self.post_id_map = None
		start = self.parameters.get("start", "random")

		self.dataset.update_status("Finding the starting point")
		found = self.find_start(start)
		if found is None:
			return
		start_vector, start_position, start_label = found

		size = min(self.parameters.get("neighbours", 1000), MAX_NEIGHBOURHOOD)
		self.dataset.update_status(f"Finding the {size:,} embeddings closest to {start_label}")
		matrix, similarities, records = self.find_neighbourhood(start_vector, size)
		if len(records) < 2:
			self.dataset.finish_with_error("Not enough embeddings to make a path (need at least 2).")
			return

		# the start itself is in its own neighbourhood; a cluster centre is not
		# an embedding, so its path starts at the embedding closest to it
		first = next((index for index, record in enumerate(records) if record["position"] == start_position),
					 int(np.argmax(similarities)))
		del similarities

		self.dataset.update_status(f"Walking a path through {len(records):,} embeddings")
		order, distances = self.walk(matrix, first)
		del matrix

		self.write_path(order, distances, records, start_label)

		summary = (f"Walked a path through {len(order):,} embeddings, starting at embedding "
				   f"{records[first]['id']} ({start_label})")
		self.dataset.update_status(summary, is_final=True)
		self.dataset.finish(len(order))

	def iterate_records(self):
		"""
		Yield each embedding record in the parent with its position and vector.

		:return:  Generator of `(position, record, vector)`, skipping records
		  without a vector
		"""
		for position, item in enumerate(self.source_dataset.iterate_items(self, get_annotations=False)):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while reading embeddings")

			record = item.original
			vector = get_vector(record)
			if vector:
				yield position, record, vector

	def find_start(self, start: str) -> tuple | None:
		"""
		Get the vector the path starts from.

		:param str start:  `random`, `embedding`, `post` or `cluster`
		:return tuple|None:  `(normalised vector, position of the starting
		  embedding or None for a cluster centre, readable description)`, or
		  `None` if the dataset was finished with an error
		"""
		if start == "cluster":
			return self.find_cluster_centre(self.parameters.get("start_cluster", 0))

		if start == "embedding":
			wanted = str(self.parameters.get("start_embedding", "")).strip()
			label = f"embedding {wanted}"

			def match(position, record):
				return str(record.get("id")) == wanted

		elif start == "post":
			wanted = str(self.parameters.get("start_post", "")).strip()
			label = f"post {wanted}"

			def match(position, record):
				return wanted in self.get_post_ids(record)

		else:
			# the seed is logged, so the same start can be found again
			seed = secrets.randbelow(2 ** 32)
			target = int(np.random.default_rng(seed).integers(max(self.source_dataset.num_rows, 1)))
			self.dataset.log(f"Picking a random start with seed {seed}")
			label = None

			# the first embedding at or after the drawn position; some items
			# may have no vector, so the drawn one need not have one itself
			def match(position, record):
				return position >= target

		for position, record, vector in self.iterate_records():
			if match(position, record):
				break
		else:
			if start != "random":
				self.dataset.finish_with_error(f"Could not find {label} in the parent dataset.")
				return None
			# drawn past the last embedding: start at the first
			found = next(self.iterate_records(), None)
			if found is None:
				self.dataset.finish_with_error("The parent dataset contains no embeddings.")
				return None
			position, record, vector = found

		if label is None:
			label = f"random embedding {record.get('id')}"
		self.dataset.log(f"Starting at embedding {record.get('id')} ({label})")

		return self.normalise(vector), position, label

	def find_cluster_centre(self, cluster: int) -> tuple | None:
		"""
		Average the embeddings of one cluster.

		:param int cluster:  Cluster number
		:return tuple|None:  `(normalised centre, None, readable description)`,
		  or `None` if the dataset was finished with an error
		"""
		total, count = None, 0
		for position, record, vector in self.iterate_records():
			if record.get("cluster") != cluster:
				continue
			# normalised first, so long vectors do not outweigh short ones
			vector = self.normalise(vector)
			total = vector if total is None else total + vector
			count += 1

		if not count:
			self.dataset.finish_with_error(f"Cluster {cluster} has no embeddings in the parent dataset.")
			return None

		self.dataset.log(f"Starting at the centre of cluster {cluster}, averaged over {count:,} embeddings")
		return self.normalise(total), None, f"cluster {cluster} centre"

	@staticmethod
	def normalise(vector) -> np.ndarray:
		"""
		Turn a vector into a float32 array of length 1.

		:param vector:  List or array of numbers
		:return np.ndarray:  Normalised vector
		"""
		vector = np.asarray(vector, dtype=np.float32)
		norm = np.linalg.norm(vector)
		return vector / norm if norm else vector

	def find_neighbourhood(self, start_vector, size: int) -> tuple:
		"""
		Keep the `size` embeddings most similar to the start.

		Reads the parent in chunks, and keeps only the closest embeddings so
		far in a fixed array: memory stays at `size` vectors plus one chunk,
		however large the parent is.

		:param start_vector:  Normalised vector to compare with
		:param int size:  Most embeddings to keep
		:return tuple:  `(matrix, similarities, records)`: the kept normalised
		  vectors, one per row; their similarity to the start; and a short
		  description of each (never the vector itself)
		"""
		dimensions = len(start_vector)
		matrix = np.empty((size, dimensions), dtype=np.float32)
		similarities = np.empty(size, dtype=np.float32)
		records = []
		read, skipped = 0, 0

		chunk_vectors, chunk_records = [], []

		def merge():
			vectors = normalise_in_place(np.asarray(chunk_vectors, dtype=np.float32))
			scores = vectors @ start_vector

			# fill empty slots first
			room = size - len(records)
			if room > 0:
				taken = min(room, len(scores))
				matrix[len(records):len(records) + taken] = vectors[:taken]
				similarities[len(records):len(records) + taken] = scores[:taken]
				records.extend(chunk_records[:taken])
				vectors, scores, rest = vectors[taken:], scores[taken:], chunk_records[taken:]
			else:
				rest = chunk_records

			if not len(scores):
				return

			# then replace the least similar kept embeddings with closer ones
			closer = np.flatnonzero(scores > similarities.min())
			if not len(closer):
				return
			combined = np.concatenate([similarities, scores[closer]])
			keep = np.argpartition(-combined, size - 1)[:size]
			incoming = keep[keep >= size] - size
			evicted = np.setdiff1d(np.arange(size), keep[keep < size], assume_unique=True)
			for slot, candidate in zip(evicted, closer[incoming]):
				matrix[slot] = vectors[candidate]
				similarities[slot] = scores[candidate]
				records[slot] = rest[candidate]

		for position, record, vector in self.iterate_records():
			if len(vector) != dimensions:
				# a vector of a different width cannot be compared; it means
				# the dataset mixes models
				skipped += 1
				continue

			chunk_vectors.append(vector)
			chunk_records.append(self.describe(position, record))
			read += 1

			if len(chunk_vectors) >= READ_CHUNK:
				merge()
				chunk_vectors, chunk_records = [], []

			if read % STATUS_EVERY == 0:
				self.dataset.update_status(f"Compared {read:,} embeddings with {size:,} closest kept")
				if self.source_dataset.num_rows:
					self.dataset.update_progress(read / self.source_dataset.num_rows / 2)

		if chunk_vectors:
			merge()

		if skipped:
			self.dataset.log(f"Skipped {skipped:,} embeddings of a different size than the start")

		kept = len(records)
		return matrix[:kept], similarities[:kept], records

	def describe(self, position: int, record: dict) -> dict:
		"""
		Keep what the output needs of an embedding record.

		:param int position:  Position of the record in the parent
		:param dict record:  Embedding record
		:return dict:  Description of the record
		"""
		return {
			"position": position,
			"id": record.get("id"),
			"text": record.get("text", ""),
			"filename": record.get("filename", ""),
			"cluster": record.get("cluster", ""),
			"post_ids": self.get_post_ids(record),
		}

	def get_post_ids(self, record: dict) -> list:
		"""
		Get the posts in the original dataset an embedding stands for.

		A text embedding's ID is its post's ID. A media file's ID is a hash of
		the file, which matches no post: it stands for the posts it appeared
		in, recorded in the embedding or else in the media archive.

		:param dict record:  Embedding record
		:return list:  Post IDs, as strings
		"""
		if "filename" not in record:
			return [str(record.get("id"))]

		post_ids = record.get("post_ids")
		if isinstance(post_ids, str):
			post_ids = [post_id.strip() for post_id in post_ids.split(",")]
		if not post_ids:
			if self.post_id_map is None:
				archive = self.get_embeddings_dataset().get_parent()
				self.post_id_map = read_post_id_map(archive.get_results_path() if archive else None,
													log=self.dataset.log)
			post_ids = self.post_id_map.get(str(record.get("id")), [])

		return [str(post_id) for post_id in post_ids if post_id]

	def get_embeddings_dataset(self):
		"""
		Get the dataset the embeddings were made in, past any clustering step.

		:return DataSet:  The embeddings dataset
		"""
		dataset = self.source_dataset
		while getattr(dataset, "type", None) == CLUSTERED_EMBEDDINGS and dataset.get_parent():
			dataset = dataset.get_parent()
		return dataset

	def walk(self, matrix, first: int) -> tuple:
		"""
		Walk from the first embedding to the nearest one not yet visited, on.

		Visited rows are masked rather than removed, and the matrix is
		compacted once half of it is visited, so steps get cheaper as the walk
		goes on without copying the matrix at every step.

		:param matrix:  Normalised vectors, one per row
		:param int first:  Row to start at
		:return tuple:  `(order, distances)`: rows in walking order, and each
		  one's cosine distance to the one before it (0 for the first)
		"""
		total = len(matrix)
		# rows of `remaining` map to rows of the original matrix
		remaining = np.arange(total)
		candidates = matrix
		visited = np.zeros(total, dtype=bool)

		order, distances = [first], [0.0]
		current = first
		visited[first] = True
		masked = 1

		for step in range(1, total):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while walking the path")

			if masked > len(remaining) // 2:
				keep = ~visited
				remaining, candidates, visited = remaining[keep], candidates[keep], visited[keep]
				masked = 0

			scores = candidates @ matrix[current]
			scores[visited] = -np.inf
			nearest = int(np.argmax(scores))

			visited[nearest] = True
			masked += 1
			current = int(remaining[nearest])
			order.append(current)
			# rounding can put identical vectors a hair below 0
			distances.append(max(0.0, float(1 - scores[nearest])))

			if step % STATUS_EVERY == 0:
				self.dataset.update_status(f"Walked {step:,} of {total:,} steps")
				self.dataset.update_progress(0.5 + step / total / 2)

		return order, distances

	def write_path(self, order: list, distances: list, records: list, start_label: str):
		"""
		Write the path to a CSV file and, if asked, annotate the top dataset.

		:param list order:  Rows in walking order
		:param list distances:  Cosine distance of each step
		:param list records:  Description per row
		:param str start_label:  Where the path started, for annotation labels
		"""
		save_annotations = self.parameters.get("save_annotations", False)
		position_label = f"latent path position (from {start_label})"
		distance_label = f"latent path distance (from {start_label})"
		annotations = []
		annotated = set()
		unmatched = 0

		fieldnames = ["position", "id", "post_ids", "text", "filename", "step_distance", "cumulative_distance"]
		if self.source_dataset.type == CLUSTERED_EMBEDDINGS:
			fieldnames.append("cluster")

		self.dataset.update_status("Writing the path")
		cumulative = 0.0
		with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as outfile:
			writer = csv.DictWriter(outfile, fieldnames=fieldnames, extrasaction="ignore")
			writer.writeheader()

			for path_position, (row, distance) in enumerate(zip(order, distances), start=1):
				record = records[row]
				cumulative += distance
				writer.writerow({
					**record,
					"position": path_position,
					"post_ids": ", ".join(record["post_ids"]),
					"step_distance": round(distance, 4),
					"cumulative_distance": round(cumulative, 4),
				})

				if not save_annotations:
					continue

				if not record["post_ids"]:
					unmatched += 1

				# a post with several media files keeps its first place on the path
				for post_id in record["post_ids"]:
					if post_id in annotated:
						continue
					annotated.add(post_id)
					annotations.append({"item_id": post_id, "label": position_label, "value": str(path_position),
										"type": "text"})
					annotations.append({"item_id": post_id, "label": distance_label,
										"value": str(round(distance, 4)), "type": "text"})

				# saved in batches as we go, so memory stays low and a run that
				# fails halfway keeps what it saved
				if len(annotations) >= self.annotation_batch_size:
					self.save_annotations(annotations)
					annotations = []

		if annotations:
			self.save_annotations(annotations)
		if save_annotations:
			self.dataset.log(f"Annotated {len(annotated):,} posts with their position on the path")
		if unmatched:
			self.dataset.log(f"{unmatched:,} files could not be linked to a post in the original dataset, so they "
							 f"were not annotated.")
