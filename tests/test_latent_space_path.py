"""
Tests for `processors/machine_learning/latent_space_path.py`: finding the
start, keeping its nearest neighbours, walking them, and the annotations.

These build the processor without a server, with stand-ins for datasets.
"""
import csv

import numpy as np
import pytest

from processors.machine_learning.latent_space_path import LatentSpacePath


class Item(dict):
	"""Stands in for a DatasetItem, whose `original` is the unmapped record."""

	@property
	def original(self):
		return self


class Collector:
	"""Stands in for the dataset the processor writes to."""

	def __init__(self, path):
		self.path, self.error, self.rows, self.key = path, None, 0, "testkey"
		self.logged = []

	def get_results_path(self):
		return self.path

	def update_status(self, message, is_final=False):
		pass

	def update_progress(self, progress):
		pass

	def log(self, message):
		self.logged.append(message)

	def finish(self, rows):
		self.rows = rows

	def finish_with_error(self, error):
		self.error = error


class Source:
	"""Stands in for the embeddings dataset the processor reads from."""

	def __init__(self, items, dataset_type="text-embeddings"):
		self.items, self.type = items, dataset_type

	@property
	def num_rows(self):
		return len(self.items)

	def get_parent(self):
		return None

	def iterate_items(self, processor=None, **kwargs):
		return iter(self.items)


def line_items(count=10, extra=None):
	"""Embeddings on a quarter circle, so neighbours follow the angle."""
	return [Item({"id": f"p{i}", "text": f"text {i}",
				  "embedding": [float(np.cos(i / 20)), float(np.sin(i / 20)), 0.0], **(extra or {}).get(i, {})})
			for i in range(count)]


def run(tmp_path, items, dataset_type="text-embeddings", **parameters):
	processor = LatentSpacePath.__new__(LatentSpacePath)
	processor.parameters = {"start": "random", "neighbours": 1000, **parameters}
	processor.dataset = Collector(tmp_path / "path.csv")
	processor.source_dataset, processor.interrupted = Source(items, dataset_type), False
	processor.saved = []
	processor.save_annotations = lambda annotations: processor.saved.extend(annotations) or len(annotations)
	processor.process()
	return processor


def read_rows(processor):
	with processor.dataset.path.open(encoding="utf-8") as infile:
		return list(csv.DictReader(infile))


def test_walk_follows_nearest_unvisited_neighbour():
	processor = LatentSpacePath.__new__(LatentSpacePath)
	processor.interrupted = False
	processor.dataset = Collector(None)

	matrix = np.array([[0.0], [1.0], [3.0], [6.0]], dtype=np.float32)
	matrix = np.hstack([np.cos(matrix / 10), np.sin(matrix / 10)]).astype(np.float32)
	order, distances = processor.walk(matrix, 1)

	# from 1: 0 is closest, then from 0 the nearest unvisited is 2, then 3
	assert order == [1, 0, 2, 3]
	assert distances[0] == 0 and all(distance >= 0 for distance in distances)


def test_walk_survives_compaction():
	processor = LatentSpacePath.__new__(LatentSpacePath)
	processor.interrupted = False
	processor.dataset = Collector(None)

	angles = np.arange(50, dtype=np.float32) / 100
	matrix = np.stack([np.cos(angles), np.sin(angles)], axis=1).astype(np.float32)
	order, _ = processor.walk(matrix, 0)

	assert order == list(range(50))


def test_path_from_embedding_id(tmp_path):
	processor = run(tmp_path, line_items(), start="embedding", start_embedding="p4")
	rows = read_rows(processor)

	assert processor.dataset.error is None
	assert rows[0]["id"] == "p4" and rows[0]["position"] == "1"
	assert {row["id"] for row in rows} == {f"p{i}" for i in range(10)}
	assert processor.dataset.rows == 10


def test_neighbourhood_keeps_only_the_closest(tmp_path):
	processor = run(tmp_path, line_items(count=40), start="embedding", start_embedding="p20", neighbours=5)
	rows = read_rows(processor)

	assert {row["id"] for row in rows} == {f"p{i}" for i in range(18, 23)}


def test_neighbourhood_keeps_the_closest_across_chunks(tmp_path, monkeypatch):
	monkeypatch.setattr("processors.machine_learning.latent_space_path.READ_CHUNK", 3)
	processor = run(tmp_path, line_items(count=40), start="embedding", start_embedding="p30", neighbours=7)
	rows = read_rows(processor)

	assert {row["id"] for row in rows} == {f"p{i}" for i in range(27, 34)}


def test_start_from_post_id_of_media_file(tmp_path):
	items = line_items(count=5, extra={i: {"filename": f"f{i}.jpg", "post_ids": [f"post{i}"]} for i in range(5)})
	processor = run(tmp_path, items, start="post", start_post="post3")

	assert read_rows(processor)[0]["id"] == "p3"


def test_start_from_cluster_centre(tmp_path):
	items = line_items(count=10, extra={i: {"cluster": 0 if i < 5 else 1} for i in range(10)})
	processor = run(tmp_path, items, dataset_type="cluster-embeddings", start="cluster", start_cluster=1)
	rows = read_rows(processor)

	# the centre of 5..9 lies closest to 7
	assert rows[0]["id"] == "p7"
	assert "cluster" in rows[0]


def test_missing_start_is_an_error(tmp_path):
	processor = run(tmp_path, line_items(), start="embedding", start_embedding="nope")
	assert "Could not find" in processor.dataset.error


def test_random_start_is_logged(tmp_path):
	processor = run(tmp_path, line_items())
	assert any("seed" in message for message in processor.dataset.logged)
	assert len(read_rows(processor)) == 10


def test_annotations_carry_position_and_distance(tmp_path):
	processor = run(tmp_path, line_items(count=5), start="embedding", start_embedding="p0", save_annotations=True)

	positions = {a["item_id"]: a["value"] for a in processor.saved if a["label"].startswith("latent path position")}
	distances = [a for a in processor.saved if a["label"].startswith("latent path distance")]

	assert positions == {"p0": "1", "p1": "2", "p2": "3", "p3": "4", "p4": "5"}
	assert len(distances) == 5
	assert all("(from embedding p0)" in a["label"] for a in processor.saved)


def test_post_keeps_its_first_place(tmp_path):
	# two media files from the same post
	items = line_items(count=3, extra={0: {"filename": "a.jpg", "post_ids": ["x"]},
								   1: {"filename": "b.jpg", "post_ids": ["x"]},
								   2: {"filename": "c.jpg", "post_ids": ["y"]}})
	processor = run(tmp_path, items, start="embedding", start_embedding="p0", save_annotations=True)

	positions = {a["item_id"]: a["value"] for a in processor.saved if a["label"].startswith("latent path position")}
	assert positions == {"x": "1", "y": "3"}


@pytest.mark.parametrize("dataset_type, has_cluster", [("text-embeddings", False), ("cluster-embeddings", True)])
def test_cluster_start_only_offered_after_clustering(dataset_type, has_cluster):
	options = LatentSpacePath.get_options(parent_dataset=Source([], dataset_type))
	assert ("cluster" in options["start"]["options"]) is has_cluster
	assert ("start_cluster" in options) is has_cluster
