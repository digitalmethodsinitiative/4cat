"""
Tests for how the embedding processors write annotations back to the top dataset:

- media files are named after a hash, so annotations have to be routed through
  the archive's `.metadata.json` to land on the posts they came from;
- labels are fixed in code rather than taken from the user;
- annotations are flushed in batches rather than held until the end.
"""
import json
import zipfile

import pytest

from processors.machine_learning.embed_images import EmbedImages
from processors.machine_learning.embed_text import GenerateTextEmbeddings
from processors.machine_learning.embed_videos import EmbedVideos
from processors.machine_learning.embedding_similarity import EmbeddingSimilarity


class Recorder:
    """Stands in for the dataset, remembering what was logged."""

    def __init__(self):
        self.messages = []

    def log(self, message):
        self.messages.append(message)

    def update_status(self, message, is_final=False):
        self.messages.append(message)


def make_archive(tmp_path, metadata):
    archive = tmp_path / "media.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        if metadata is not None:
            handle.writestr(".metadata.json", json.dumps(metadata))
        handle.writestr("readme.txt", "not metadata")
    return archive


def make_processor(cls, tmp_path, metadata):
    processor = cls.__new__(cls)
    processor.dataset = Recorder()
    processor.source_file = make_archive(tmp_path, metadata)
    return processor


# --------------------------------------------------------------------------- #
# resolving media files to the posts they came from

def test_post_id_map_links_filenames_to_posts(tmp_path):
    """
    A media archive is keyed by source URL; the filename is a hash. Annotating
    the hash would attach the value to an item that does not exist.
    """
    processor = make_processor(EmbedVideos, tmp_path, {
        "https://example.test/a": {"post_ids": ["p1", "p2"], "files": [{"filename": "abc123.mp4"}]},
        "https://example.test/b": {"post_ids": ["p3"], "files": [{"filename": "def456.mp4"}]},
    })

    assert processor.load_post_id_map() == {"abc123": ["p1", "p2"], "def456": ["p3"]}


def test_post_id_map_handles_several_files_per_post(tmp_path):
    """One download can write a video and a thumbnail; both map to the post."""
    processor = make_processor(EmbedVideos, tmp_path, {
        "https://example.test/a": {
            "post_ids": ["p1"],
            "files": [{"filename": "abc.mp4"}, {"filename": "abc.jpg"}],
        },
    })

    mapping = processor.load_post_id_map()
    assert mapping == {"abc": ["p1"]}


def test_post_id_map_survives_a_missing_or_broken_metadata_file(tmp_path):
    """An archive without metadata must not stop the run, only the annotations."""
    assert make_processor(EmbedImages, tmp_path, None).load_post_id_map() == {}

    processor = make_processor(EmbedImages, tmp_path, {})
    assert processor.load_post_id_map() == {}


def test_post_id_map_ignores_entries_without_files(tmp_path):
    """A failed download leaves an entry behind with no files written."""
    processor = make_processor(EmbedImages, tmp_path, {
        "https://example.test/ok": {"post_ids": ["p1"], "files": [{"filename": "ok.jpg"}]},
        "https://example.test/failed": {"post_ids": ["p2"], "success": False},
    })

    assert processor.load_post_id_map() == {"ok": ["p1"]}


def test_post_id_map_without_a_source_archive(tmp_path):
    processor = EmbedImages.__new__(EmbedImages)
    processor.dataset = Recorder()
    processor.source_file = None
    assert processor.load_post_id_map() == {}


# --------------------------------------------------------------------------- #
# similarity annotations

class FakeSimilarity(EmbeddingSimilarity):
    """Captures annotations instead of writing them to the database."""

    def __init__(self, batch_size=10):
        self.dataset = Recorder()
        self.annotation_batch_size = batch_size
        self.batches = []

    def save_annotations(self, annotations, **kwargs):
        self.batches.append(list(annotations))
        return len(annotations)


def make_results(count, posts_per_item=1):
    return [{
        "id": f"hash{i}",
        "post_ids": [f"p{i}_{n}" for n in range(posts_per_item)],
        "similarity": 0.5,
    } for i in range(count)]


def test_similarity_annotates_posts_not_filenames():
    processor = FakeSimilarity()
    processor.save_similarity_annotations(make_results(3, posts_per_item=2), "cats")

    item_ids = [a["item_id"] for batch in processor.batches for a in batch]
    assert len(item_ids) == 6
    assert not any(i.startswith("hash") for i in item_ids)


def test_similarity_flushes_in_batches():
    """Held to the end, a large dataset hands the database one enormous list."""
    processor = FakeSimilarity(batch_size=10)
    processor.save_similarity_annotations(make_results(25), "cats")

    assert len(processor.batches) > 1
    assert sum(len(b) for b in processor.batches) == 25
    assert all(len(b) <= 20 for b in processor.batches)


def test_similarity_label_is_fixed_but_names_the_query():
    processor = FakeSimilarity()
    processor.save_similarity_annotations(make_results(1), "pictures of cats")

    label = processor.batches[0][0]["label"]
    assert label == "cosine similarity to 'pictures of cats'"


def test_similarity_label_truncates_a_long_query():
    """The query can be a whole paragraph; the label still has to be readable."""
    processor = FakeSimilarity()
    processor.save_similarity_annotations(make_results(1), "a " * 200)

    label = processor.batches[0][0]["label"]
    assert len(label) < 60 and label.endswith("…'")


def test_similarity_skips_empty_post_ids():
    processor = FakeSimilarity()
    processor.save_similarity_annotations(
        [{"id": "x", "post_ids": [None, "", "p1"], "similarity": 0.5}], "cats")

    assert [a["item_id"] for a in processor.batches[0]] == ["p1"]


@pytest.mark.parametrize("processor", (EmbedVideos, EmbedImages))
def test_media_processors_declare_a_batch_size(processor):
    assert isinstance(processor.annotation_batch_size, int)
    assert processor.annotation_batch_size > 0


# --------------------------------------------------------------------------- #
# text embeddings: the item is already a post, so no metadata lookup is needed

class FakeText(GenerateTextEmbeddings):
    """Captures annotations instead of writing them to the database."""

    def __init__(self, batch_size=10):
        self.dataset = Recorder()
        self.annotation_batch_size = batch_size
        self.annotations = []
        self.save_annotations_enabled = True
        self.batches = []

    def save_annotations(self, annotations, **kwargs):
        self.batches.append((list(annotations), kwargs))
        return len(annotations)


def test_text_annotations_flush_when_the_buffer_fills():
    processor = FakeText(batch_size=10)

    for i in range(9):
        processor.annotations.append({"item_id": f"p{i}"})
        processor.flush_annotations()
    assert processor.batches == [], "flushed before the buffer was full"

    processor.annotations.append({"item_id": "p9"})
    processor.flush_annotations()
    assert len(processor.batches) == 1 and len(processor.batches[0][0]) == 10
    assert processor.annotations == [], "buffer not cleared after flushing"


def test_text_annotations_are_hidden_in_the_explorer():
    """A vector is data for computation, not something a reader can parse."""
    processor = FakeText(batch_size=1)
    processor.annotations.append({"item_id": "p1"})
    processor.flush_annotations()

    assert processor.batches[0][1].get("hide_in_explorer") is True


def test_text_annotations_force_writes_a_partial_buffer():
    """The last batch is rarely full; without force it would be dropped."""
    processor = FakeText(batch_size=100)
    processor.annotations.extend([{"item_id": "p1"}, {"item_id": "p2"}])

    processor.flush_annotations()
    assert processor.batches == []

    processor.flush_annotations(force=True)
    assert len(processor.batches[0][0]) == 2


def test_text_flush_on_an_empty_buffer_writes_nothing():
    processor = FakeText()
    processor.flush_annotations(force=True)
    assert processor.batches == []


# --------------------------------------------------------------------------- #
# the three processors form one family

ALL_EMBEDDERS = (GenerateTextEmbeddings, EmbedVideos, EmbedImages)


@pytest.mark.parametrize("processor", ALL_EMBEDDERS)
def test_option_label_matches_what_is_written(processor):
    """
    The form renders the option label as "Add <label> as annotations", so a
    label that differs from the written one promises a column that never
    appears.
    """
    option = processor.get_options(config=None)["save_annotations"]
    assert option["label"] == processor.annotation_label
    assert option["hide_in_explorer"] is True
    assert option["default"] is False


def test_every_embedder_has_a_distinct_label():
    labels = [p.annotation_label for p in ALL_EMBEDDERS]
    assert len(set(labels)) == len(labels), labels


# --------------------------------------------------------------------------- #
# resolving post IDs downstream, where the mapper has already been applied

def test_map_item_carries_post_ids_through():
    """
    `iterate_items()` hands processors the *mapped* item. A field the mapper
    drops is invisible downstream, which silently sent similarity scores to the
    filename hash instead of the posts.
    """
    record = {"id": "hash1", "text": "a.mp4", "filename": "a.mp4", "post_ids": ["p1", "p2"],
              "embedding": [0.1], "dimensions": 1, "model": "m",
              "original_bytes": 1, "sent_bytes": 1, "time_created": "t"}

    for processor in (EmbedVideos, EmbedImages):
        mapped = processor.map_item(record).get_item_data()
        assert mapped["post_ids"] == "p1, p2", processor.type


def test_post_ids_survive_the_round_trip_through_the_mapper():
    record = {"id": "hash1", "text": "a.mp4", "filename": "a.mp4", "post_ids": ["p1", "p2"],
              "embedding": [0.1], "dimensions": 1, "model": "m",
              "original_bytes": 1, "sent_bytes": 1, "time_created": "t"}
    mapped = EmbedVideos.map_item(record).get_item_data()

    assert EmbeddingSimilarity.resolve_post_ids(mapped, {}) == ["p1", "p2"]


@pytest.mark.parametrize("item,mapping,expected", [
    # recorded on the item itself, as a list (raw NDJSON)
    ({"id": "hash1", "post_ids": ["p1", "p2"]}, {}, ["p1", "p2"]),
    # recorded as the comma-separated string the mapper produces
    ({"id": "hash1", "post_ids": "p1, p2"}, {}, ["p1", "p2"]),
    # not recorded: fall back to what the archive metadata says
    ({"id": "hash2"}, {"hash2": ["p3"]}, ["p3"]),
    # a text embedding: the item already is the post
    ({"id": "post42"}, {}, ["post42"]),
    # media the metadata does not know: better its own id than nothing
    ({"id": "hash9"}, {"hash1": ["p1"]}, ["hash9"]),
    # blanks must not become annotations on an empty item
    ({"id": "hash1", "post_ids": "p1, , p2"}, {}, ["p1", "p2"]),
    ({"id": None}, {}, []),
])
def test_resolve_post_ids_covers_every_parent_shape(item, mapping, expected):
    assert EmbeddingSimilarity.resolve_post_ids(item, mapping) == expected


def test_similarity_reads_metadata_from_the_media_archive(tmp_path):
    """The archive is the parent of the embeddings, i.e. the grandparent here."""
    archive = make_archive(tmp_path, {
        "https://example.test/1": {"post_ids": ["p1", "p2"], "files": [{"filename": "hash1.mp4"}]},
    })

    class Parent:
        def get_results_path(self):
            return archive

    class Source:
        def get_parent(self):
            return Parent()

    processor = EmbeddingSimilarity.__new__(EmbeddingSimilarity)
    processor.dataset = Recorder()
    processor.source_dataset = Source()

    assert processor.load_post_id_map() == {"hash1": ["p1", "p2"]}


def test_similarity_on_a_text_parent_needs_no_metadata(tmp_path):
    """A text embedding's parent is a table, not an archive; that is not a failure."""
    table = tmp_path / "texts.csv"
    table.write_text("id,body\n1,hello\n", encoding="utf-8")

    class Parent:
        def get_results_path(self):
            return table

    class Source:
        def __init__(self, parent):
            self.parent = parent

        def get_parent(self):
            return self.parent

    processor = EmbeddingSimilarity.__new__(EmbeddingSimilarity)
    processor.dataset = Recorder()

    processor.source_dataset = Source(Parent())
    assert processor.load_post_id_map() == {}

    processor.source_dataset = Source(None)
    assert processor.load_post_id_map() == {}


# --------------------------------------------------------------------------- #
# similarity on clustered embeddings

def test_similarity_runs_on_clustered_embeddings(tmp_path, monkeypatch):
    """
    Clustering sits between the embeddings and the similarity step. The model
    and the media archive belong to the embeddings above it, and the output
    gains the cluster of each item.
    """
    import csv
    from processors.machine_learning import embedding_similarity as module

    archive_path = make_archive(tmp_path, {
        "https://example.test/1": {"post_ids": ["p1", "p2"], "files": [{"filename": "hash1.mp4"}]},
    })

    class Node:
        def __init__(self, dataset_type, parameters=None, parent=None, path=None):
            self.type, self.parameters, self.parent, self.path = dataset_type, parameters or {}, parent, path

        def get_parent(self):
            return self.parent

        def get_results_path(self):
            return self.path

    archive = Node("video-downloader", path=archive_path)
    embeddings = Node("video-embeddings", parameters={"model": "vllm-test-model"}, parent=archive)

    class Clustered(Node):
        num_rows = 2

        def iterate_items(self, processor=None, **kwargs):
            return iter([
                {"id": "hash1", "text": "hash1.mp4", "filename": "hash1.mp4", "post_ids": "", "cluster": 3,
                 "embedding": [1.0, 0.0]},
                {"id": "hash2", "text": "hash2.mp4", "filename": "hash2.mp4", "post_ids": "", "cluster": -1,
                 "embedding": [0.0, 1.0]},
            ])

    class Output(Recorder):
        def __init__(self):
            super().__init__()
            self.path, self.error, self.rows = tmp_path / "similarity.csv", None, 0

        def get_results_path(self):
            return self.path

        def update_progress(self, progress):
            pass

        def finish(self, rows):
            self.rows = rows

        def finish_with_error(self, error):
            self.error = error

    class Config:
        def get(self, key, default=None):
            return {
                "llm.available_models": {"vllm-test-model": {"local_id": "m", "server": "s"}},
                "llm.enabled_models": ["vllm-test-model"],
                "llm.servers": {"s": {"type": "openai-like"}},
            }.get(key, default)

    class Client:
        def embed(self, model_id, inputs, **kwargs):
            return [[1.0, 0.0]]

    monkeypatch.setattr(module.LLMServerClient, "get_client", staticmethod(lambda *args, **kwargs: Client()))

    processor = EmbeddingSimilarity.__new__(EmbeddingSimilarity)
    processor.dataset, processor.config, processor.log, processor.interrupted = Output(), Config(), None, False
    processor.source_dataset = Clustered("cluster-embeddings", parent=embeddings)
    processor.parameters = {"query_text": "a cat", "sort": True, "save_annotations": False}
    processor.process()

    assert processor.dataset.error is None, processor.dataset.error
    with processor.dataset.path.open(encoding="utf-8") as infile:
        rows = list(csv.DictReader(infile))

    assert [row["id"] for row in rows] == ["hash1", "hash2"]
    assert [row["cluster"] for row in rows] == ["3", "-1"]
    # the posts behind the file come from the archive two steps up
    assert rows[0]["post_ids"] == "p1, p2"
