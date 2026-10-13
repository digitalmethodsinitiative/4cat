"""
Tests for the media-embedding processors:

- `processors/machine_learning/embed_media.py` — the shared base, which must
  stay abstract so it is never registered as a processor in its own right.
- `embed_videos.py` / `embed_images.py` — that both keep the same option shape
  and wording, and that media-specific behaviour stays media-specific.
- `reduce_embeddings.py` and `embedding_map.py` — reduction to N dimensions,
  and the map drawn from a two-dimensional reduction.

These import the processor classes directly and never touch a server.
"""
import inspect
from pathlib import Path

import pytest

from processors.machine_learning.embed_images import EmbedImages
from processors.machine_learning.embed_media import EmbedMedia
from processors.machine_learning.embed_videos import EmbedVideos

SUBCLASSES = (EmbedVideos, EmbedImages)


# --------------------------------------------------------------------------- #
# the shared base must never become a processor of its own

def test_base_stays_abstract():
    """
    `ModuleCollector.is_4cat_class()` skips classes `inspect.isabstract()`
    reports. If `prepare_media` ever gained a body, the base would register as a
    real processor and show up in the interface as an option nobody can run.
    """
    assert inspect.isabstract(EmbedMedia)
    assert "prepare_media" in EmbedMedia.__abstractmethods__


def test_base_claims_no_job_type_of_its_own():
    """
    The base inherits BasicProcessor's placeholder `type` rather than declaring
    one, so abstractness is the only thing keeping it out of the registry - if
    that guard goes, this placeholder is what would get registered.
    """
    from backend.lib.processor import BasicProcessor
    assert EmbedMedia.type == BasicProcessor.type
    assert "type" not in EmbedMedia.__dict__


@pytest.mark.parametrize("processor", SUBCLASSES)
def test_subclasses_are_concrete_and_typed(processor):
    assert not inspect.isabstract(processor)
    # declared on the subclass itself, not inherited from the base
    assert "type" in processor.__dict__
    assert processor.type and processor.extension == "ndjson"


# --------------------------------------------------------------------------- #
# option shape is shared, media options sit in the middle

@pytest.mark.parametrize("processor", SUBCLASSES)
def test_shared_options_wrap_the_media_specific_ones(processor):
    keys = list(processor.get_options(config=None).keys())
    assert keys[:3] == ["model_info", "model", "instruction"]
    assert keys[-2:] == ["amount", "save_annotations"]
    # everything between the two is contributed by the subclass
    assert set(keys[3:-2]) == set(processor.get_media_options().keys())


@pytest.mark.parametrize("processor", SUBCLASSES)
def test_wording_follows_the_media_label(processor):
    options = processor.get_options(config=None)
    label, plural = processor.media_label, processor.media_label_plural

    assert options["instruction"]["default"] == f"Represent the {label}."
    assert options["amount"]["help"] == f"No. of {plural}"
    assert f"**{label}**" in options["model_info"]["help"]


def test_video_and_image_options_differ_where_they_should():
    video = set(EmbedVideos.get_media_options())
    image = set(EmbedImages.get_media_options())

    # frame rate and duration are meaningless for a still image
    assert {"fps", "max_duration", "crf"} <= video
    assert not {"fps", "max_duration", "crf"} & image
    # both scale down, so both expose a pixel cap
    assert "max_size" in video and "max_size" in image


# --------------------------------------------------------------------------- #
# media-specific behaviour

def test_images_skip_vector_files(tmp_path):
    """SVGs are common in image archives and Pillow cannot rasterise them."""
    processor = EmbedImages.__new__(EmbedImages)
    assert processor.skip_reason(tmp_path / "logo.svg") == "SVG files cannot be embedded"
    assert processor.skip_reason(tmp_path / "LOGO.SVG") == "SVG files cannot be embedded"
    assert processor.skip_reason(tmp_path / "photo.jpg") is None


def test_videos_skip_nothing_by_name(tmp_path):
    processor = EmbedVideos.__new__(EmbedVideos)
    assert processor.skip_reason(tmp_path / "clip.mp4") is None


@pytest.mark.parametrize("processor", SUBCLASSES)
def test_annotation_label_is_fixed_per_media_type(processor):
    """
    Not user-editable: a vector only means something next to the model that
    produced it, so a free-form label invites mismatched columns.
    """
    option = processor.get_options(config=None)["save_annotations"]
    assert option["type"] == "annotation"
    assert option["label"] == processor.annotation_label
    assert processor.media_label.split()[0].lower() in processor.annotation_label.lower()


def test_annotation_labels_do_not_collide():
    assert EmbedVideos.annotation_label != EmbedImages.annotation_label


def test_working_filenames_do_not_collide():
    """Each processor compresses into its own file in the staging area."""
    assert EmbedVideos.working_filename != EmbedImages.working_filename


# --------------------------------------------------------------------------- #
# output shape, shared with text-embeddings so downstream processors chain

@pytest.mark.parametrize("processor", SUBCLASSES)
def test_map_item_matches_the_text_embedding_shape(processor):
    mapped = processor.map_item({
        "id": "abc", "text": "abc.mp4", "filename": "abc.mp4",
        "embedding": [0.1, 0.2, 0.3], "dimensions": 3, "model": "some-model",
        "original_bytes": 100, "sent_bytes": 50, "time_created": "2026-01-01 00:00:00",
    }).get_item_data()

    assert mapped["embedding"] == "0.1 0.2 0.3"
    assert mapped["dimensions"] == 3
    for key in ("id", "text", "model", "timestamp"):
        assert key in mapped


# --------------------------------------------------------------------------- #
# the map has to survive the round trip to the preview pane

class Item(dict):
    """Stands in for a DatasetItem, whose `original` is the unmapped record."""

    @property
    def original(self):
        return self


class Collector:
    """Stands in for the dataset a processor writes to."""

    def __init__(self, path, parameters=None):
        self.path, self.error, self.rows, self.key = path, None, 0, "testkey"
        self.parameters = parameters or {}

    def get_results_path(self):
        return self.path

    def update_status(self, message, is_final=False):
        pass

    def update_progress(self, progress):
        pass

    def log(self, message):
        pass

    def finish(self, rows):
        self.rows = rows

    def finish_with_error(self, error):
        self.error = error


class Source:
    """Stands in for the dataset a processor reads from."""

    def __init__(self, items, parameters=None, parent=None, dataset_type="reduce-embeddings"):
        self.items, self.parameters, self._parent = items, parameters or {}, parent
        self.type = dataset_type

    @property
    def num_rows(self):
        return len(self.items)

    def get_parent(self):
        return self._parent

    def iterate_items(self, processor=None, **kwargs):
        return iter(self.items)


def make_embeddings(texts, dimensions=8):
    return [Item({"id": i, "text": text, "embedding": [float((i * 7 + j) % 11) for j in range(dimensions)]})
            for i, text in enumerate(texts)]


def run_reducer(tmp_path, items, **parameters):
    """Reduce the given embedding items and return the processor."""
    from processors.machine_learning.reduce_embeddings import ReduceEmbeddings

    processor = ReduceEmbeddings.__new__(ReduceEmbeddings)
    processor.parameters = {"algorithm": "pca", "dimensions": 2, "amount": 0, **parameters}
    processor.dataset = Collector(tmp_path / "reduced.ndjson", processor.parameters)
    processor.source_dataset, processor.interrupted = Source(items), False
    processor.process()
    return processor


def read_reduced(processor):
    import json
    with processor.dataset.path.open(encoding="utf-8") as infile:
        return [Item(json.loads(line)) for line in infile]


def build_map(tmp_path, texts, algorithm="pca"):
    """Reduce embeddings for the given hover texts, map them and return the HTML."""
    from processors.visualisation.embedding_map import EmbeddingMap

    reducer = run_reducer(tmp_path, make_embeddings(texts), algorithm=algorithm)
    assert reducer.dataset.error is None, reducer.dataset.error

    processor = EmbeddingMap.__new__(EmbeddingMap)
    processor.dataset = Collector(tmp_path / "map.html")
    processor.source_dataset = Source(read_reduced(reducer), parameters=reducer.parameters)
    processor.interrupted = False
    processor.parameters = {"max_text_length": 100}
    processor.process()

    assert processor.dataset.error is None, processor.dataset.error
    return processor.dataset.path


@pytest.mark.parametrize("algorithm,dimensions", [("pca", 1), ("pca", 3), ("umap", 3), ("tsne", 3)])
def test_reducer_writes_the_requested_number_of_dimensions(tmp_path, algorithm, dimensions):
    texts = [f"item {i}" for i in range(12)]
    reducer = run_reducer(tmp_path, make_embeddings(texts, dimensions=8), algorithm=algorithm, dimensions=dimensions,
                          n_neighbors=5, perplexity=3)
    assert reducer.dataset.error is None, reducer.dataset.error

    records = read_reduced(reducer)
    assert reducer.dataset.rows == len(records) == 12
    assert all(len(record["coordinates"]) == dimensions for record in records)
    # the embedding itself stays behind; only what labels and traces an item
    assert [record["text"] for record in records] == texts
    assert "embedding" not in records[0]


def test_reducer_keeps_media_fields_for_thumbnails_and_tracing(tmp_path):
    items = make_embeddings([f"f{i}.jpg" for i in range(5)])
    for item in items:
        item.update({"filename": item["text"], "post_ids": [f"post-{item['id']}"]})

    record = read_reduced(run_reducer(tmp_path, items))[0]
    assert record["filename"] == "f0.jpg" and record["post_ids"] == ["post-0"]


def test_reducer_maps_one_column_per_dimension():
    from common.lib.item_mapping import MissingMappedField
    from processors.machine_learning.reduce_embeddings import ReduceEmbeddings

    row = ReduceEmbeddings.map_item({"id": "a", "text": "t", "coordinates": [0.5, -1.0, 2.0],
                                     "algorithm": "umap"}).get_item_data()
    assert (row["dimension_1"], row["dimension_2"], row["dimension_3"]) == (0.5, -1.0, 2.0)
    assert "dimension_4" not in row
    # text embeddings have no files: missing, not an empty filename
    assert isinstance(ReduceEmbeddings.map_item({"id": "a", "coordinates": []}).data["filename"], MissingMappedField)


@pytest.mark.parametrize("dimensions,count,fragment", [(8, 12, "cannot be"), (5, 6, "needs at least")])
def test_reducer_refuses_impossible_dimensions(tmp_path, dimensions, count, fragment):
    reducer = run_reducer(tmp_path, make_embeddings([str(i) for i in range(count)], dimensions=8),
                          dimensions=dimensions)
    assert fragment in reducer.dataset.error


def test_reducer_refuses_tsne_beyond_three_dimensions():
    from common.lib.exceptions import QueryParametersException
    from processors.machine_learning.reduce_embeddings import ReduceEmbeddings

    with pytest.raises(QueryParametersException):
        ReduceEmbeddings.validate_query({"algorithm": "tsne", "dimensions": 4}, None, None)
    assert ReduceEmbeddings.validate_query({"algorithm": "umap", "dimensions": 4}, None, None)


NON_ASCII = ["Álvaro posted this \U0001F44D", "café au lait", "你好世界",
             "plain ascii", "naïve résumé", "\U0001F389 party", "ordinary", "Ñandú"]


def test_map_output_is_utf8_with_non_ascii_intact(tmp_path):
    """
    Post text routinely carries emoji and accents. The file must be readable as
    UTF-8 and keep them, since the preview pane reads it straight back.
    """
    path = build_map(tmp_path, NON_ASCII)

    content = path.read_text(encoding="utf-8")
    assert "\U0001F44D" in content and "你好世界" in content


def test_map_declares_its_encoding(tmp_path):
    """
    A downloaded file has no page to inherit a charset from, so it has to say so
    itself - and the declaration must come early enough for the parser to act on
    it.
    """
    path = build_map(tmp_path, NON_ASCII)
    head = path.read_text(encoding="utf-8")[:1024]
    assert 'charset="utf-8"' in head.lower()


def test_preview_route_reads_dataset_files_as_utf8():
    """
    A bare open() decodes with the locale encoding. On a non-UTF-8 locale
    (cp1252 on Windows) an accented capital or emoji in the data raises
    UnicodeDecodeError, and the preview 500s instead of rendering - which looks
    like an intermittent visualisation failure.
    """
    import re
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "webtool/views/views_dataset.py"
    body = source.read_text(encoding="utf-8")
    start = body.index("def preview_items(")
    end = body.index("\n@component.route", start)
    preview = body[start:end]

    bare_opens = re.findall(r"\w+\.open\(\s*\)", preview)
    assert not bare_opens, f"dataset files opened without an encoding: {bare_opens}"


# --------------------------------------------------------------------------- #
# thumbnails live in their own processor, and the map only reads what it made

class FakeDataset:
    """Stands in for a DataSet, for the bits these processors touch."""

    def __init__(self, tmp_path, name="d", dataset_type="media-thumbnails",
                 parameters=None, rows=0, finished=True, parent=None, children=()):
        self.path = tmp_path / f"{name}.zip"
        self.type = dataset_type
        self.parameters = parameters or {}
        self.num_rows = rows
        self.key = name
        self._finished, self._parent, self._children = finished, parent, list(children)
        self.error, self.logs = None, []

    def get_results_path(self):
        return self.path

    def get_staging_area(self):
        staging = self.path.parent / f"staging-{self.key}"
        staging.mkdir(exist_ok=True)
        return staging

    def is_finished(self):
        return self._finished

    def get_parent(self):
        return self._parent

    def get_children(self):
        return self._children

    def top_parent(self):
        return self._parent.top_parent() if self._parent else self

    def get_columns(self):
        return []

    def update_status(self, message, is_final=False):
        pass

    def update_progress(self, progress):
        pass

    def log(self, message):
        self.logs.append(message)

    def finish(self, rows):
        self.num_rows = rows

    def finish_with_error(self, error):
        self.error = error

    def finish_with_warning(self, rows, warning):
        self.num_rows, self.error = rows, None


def make_sprite(tmp_path, names, size=32, name="sprite"):
    """Run the real thumbnail processor over a folder of images."""
    from PIL import Image
    from processors.visualisation.media_thumbnails import MediaThumbnails

    media = tmp_path / f"media-{name}"
    media.mkdir(exist_ok=True)

    class Item:
        def __init__(self, file):
            self.file = file

    items = []
    for i, filename in enumerate(names):
        path = media / filename
        Image.new("RGB", (100, 60), (i * 40 % 255, 60, 90)).save(path)
        items.append(Item(path))

    class Source:
        num_rows = len(items)

        def iterate_items(self, processor=None, **kwargs):
            return iter(items)

    class Config:
        def get(self, key, default=None):
            return "ffmpeg" if key == "video-downloader.ffmpeg_path" else default

    processor = MediaThumbnails.__new__(MediaThumbnails)
    processor.dataset = FakeDataset(tmp_path, name=name)
    processor.source_dataset, processor.config, processor.interrupted = Source(), Config(), False
    processor.parameters = {"thumbnail_size": size, "amount": 0}
    processor.process()
    return processor.dataset


def test_thumbnails_are_packed_and_keyed_by_filename(tmp_path):
    """
    Keyed by name, not position: a map may cap or filter its items, and
    positional tiles would then line up with the wrong pictures.
    """
    from processors.visualisation.media_thumbnails import MediaThumbnails

    dataset = make_sprite(tmp_path, ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"], size=32)
    assert dataset.error is None and dataset.num_rows == 5

    sprite = MediaThumbnails.read_sprite(dataset)
    assert sprite["tile"] == 32
    assert set(sprite["tiles"]) == {"a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"}
    assert sorted(sprite["tiles"].values()) == [0, 1, 2, 3, 4]
    assert sprite["uri"].startswith("data:image/jpeg;base64,")


def test_sprite_sheet_is_a_square_grid_of_square_tiles(tmp_path):
    import base64
    import io
    from PIL import Image
    from processors.visualisation.media_thumbnails import MediaThumbnails

    dataset = make_sprite(tmp_path, [f"f{i}.jpg" for i in range(7)], size=24, name="grid")
    sprite = MediaThumbnails.read_sprite(dataset)

    sheet = Image.open(io.BytesIO(base64.b64decode(sprite["uri"].split(",", 1)[1])))
    assert sheet.width == sprite["cols"] * 24
    assert sheet.height % 24 == 0


def test_read_sprite_rejects_anything_that_is_not_one(tmp_path):
    from processors.visualisation.media_thumbnails import MediaThumbnails

    missing = FakeDataset(tmp_path, name="missing")
    assert MediaThumbnails.read_sprite(missing) is None

    not_a_zip = FakeDataset(tmp_path, name="plain")
    not_a_zip.path.write_text("not a zip", encoding="utf-8")
    assert MediaThumbnails.read_sprite(not_a_zip) is None

    import zipfile
    wrong_contents = FakeDataset(tmp_path, name="wrong")
    with zipfile.ZipFile(wrong_contents.path, "w") as handle:
        handle.writestr("something.txt", "x")
    assert MediaThumbnails.read_sprite(wrong_contents) is None


# --------------------------------------------------------------------------- #
# the map finds sprite sheets made from the same media, and offers them

def test_reducer_accepts_every_embedding_type():
    """Image embeddings were missing, which is where thumbnails matter most."""
    from processors.machine_learning.reduce_embeddings import ReduceEmbeddings

    assert ReduceEmbeddings.compatibility.types == {"text-embeddings", "video-embeddings", "image-embeddings",
                                                    "cluster-embeddings"}


def test_map_only_runs_on_two_dimensional_reductions(monkeypatch):
    from processors.visualisation import embedding_map as module
    from processors.machine_learning.reduce_embeddings import ReduceEmbeddings

    # FakeDataset stands in for a DataSet here, so the check treats it as one
    monkeypatch.setattr(module, "DataSet", FakeDataset)
    for dimensions, expected in ((2, True), (3, False), (1, False)):
        reduced = FakeDataset(Path("."), dataset_type="reduce-embeddings", parameters={"dimensions": dimensions})
        assert module.EmbeddingMap.is_compatible_with(reduced) is expected

    embeddings = FakeDataset(Path("."), dataset_type="text-embeddings")
    assert module.EmbeddingMap.is_compatible_with(embeddings) is False

    # as a suggested follow-up, before any dataset exists
    assert module.EmbeddingMap.is_compatible_with(ReduceEmbeddings) is True


def test_map_finds_sprites_beside_the_embeddings(tmp_path):
    """
    A sprite sheet is a child of the media archive, so it is a *sibling* of the
    embeddings - one extraction then serves every map of that media.
    """
    from processors.visualisation.embedding_map import EmbeddingMap

    sprite = FakeDataset(tmp_path, name="sprite1", parameters={"thumbnail_size": 48}, rows=120)
    unfinished = FakeDataset(tmp_path, name="sprite2", parameters={"thumbnail_size": 96}, finished=False)
    unrelated = FakeDataset(tmp_path, name="other", dataset_type="image-embeddings")
    archive = FakeDataset(tmp_path, name="archive", dataset_type="video-downloader",
                          children=[sprite, unfinished, unrelated])
    embeddings = FakeDataset(tmp_path, name="emb", dataset_type="video-embeddings", parent=archive)
    reduced = FakeDataset(tmp_path, name="red", dataset_type="reduce-embeddings", parent=embeddings)

    found = EmbeddingMap.find_sprite_datasets(reduced)
    assert list(found) == ["sprite1"], "only finished sprite sheets should be offered"
    assert "48px" in found["sprite1"] and "120" in found["sprite1"]


@pytest.mark.parametrize("dataset_type", ["text-embeddings", "tokenise-posts"])
def test_map_offers_no_sprites_for_non_media(tmp_path, dataset_type):
    from processors.visualisation.embedding_map import EmbeddingMap

    sprite = FakeDataset(tmp_path, name="sprite1", parameters={"thumbnail_size": 48}, rows=5)
    archive = FakeDataset(tmp_path, name="archive", children=[sprite])
    parent = FakeDataset(tmp_path, name="p", dataset_type=dataset_type, parent=archive)
    reduced = FakeDataset(tmp_path, name="red", dataset_type="reduce-embeddings", parent=parent)

    assert EmbeddingMap.find_sprite_datasets(reduced) == {}
    assert EmbeddingMap.find_sprite_datasets(None) == {}


def test_map_option_is_a_picker_when_sprites_exist(tmp_path):
    from processors.visualisation.embedding_map import EmbeddingMap

    sprite = FakeDataset(tmp_path, name="sprite1", parameters={"thumbnail_size": 48}, rows=9)
    archive = FakeDataset(tmp_path, name="archive", children=[sprite])
    embeddings = FakeDataset(tmp_path, name="emb", dataset_type="image-embeddings", parent=archive)
    reduced = FakeDataset(tmp_path, name="red", dataset_type="reduce-embeddings", parent=embeddings)

    options = EmbeddingMap.get_options(parent_dataset=reduced, config=None)
    assert options["thumbnails"]["type"] == "choice"
    # "no thumbnails" has to stay available, and be the default
    assert options["thumbnails"]["default"] == ""
    assert "sprite1" in options["thumbnails"]["options"]


def test_map_explains_how_to_get_thumbnails_when_there_are_none(tmp_path):
    """Otherwise the option is simply absent and nobody knows it exists."""
    from processors.visualisation.embedding_map import EmbeddingMap

    archive = FakeDataset(tmp_path, name="archive", children=[])
    embeddings = FakeDataset(tmp_path, name="emb", dataset_type="video-embeddings", parent=archive)
    reduced = FakeDataset(tmp_path, name="red", dataset_type="reduce-embeddings", parent=embeddings)

    options = EmbeddingMap.get_options(parent_dataset=reduced, config=None)
    assert "thumbnails" not in options
    assert "Generate thumbnails" in options["thumbnails_info"]["help"]


# --------------------------------------------------------------------------- #
# lining a sprite sheet up with the points

def map_reading_sprite(tmp_path, sprite_dataset, key="sprite"):
    from processors.visualisation.embedding_map import EmbeddingMap

    archive = FakeDataset(tmp_path, name="archive", dataset_type="video-downloader")
    embeddings = FakeDataset(tmp_path, name="emb", dataset_type="video-embeddings", parent=archive)

    class Config:
        def get(self, key, default=None):
            return default

    processor = EmbeddingMap.__new__(EmbeddingMap)
    processor.dataset = FakeDataset(tmp_path, name="map")
    processor.source_dataset, processor.config = embeddings, Config()
    processor.parameters = {"thumbnails": key}
    processor.db, processor.modules = None, None
    return processor


def test_sprite_tiles_line_up_with_the_points(tmp_path, monkeypatch):
    from processors.visualisation import embedding_map as module

    sprite_dataset = make_sprite(tmp_path, ["a.jpg", "b.jpg", "c.jpg"], size=16, name="line")
    monkeypatch.setattr(module, "DataSet", lambda **kwargs: sprite_dataset)

    processor = map_reading_sprite(tmp_path, sprite_dataset)
    # "gone.jpg" has no tile, and the order differs from the sheet's
    result = processor.load_sprite(["c.jpg", "gone.jpg", "a.jpg"])

    assert result["tiles"][1] == -1
    assert result["tiles"][0] != result["tiles"][2]
    assert result["tile"] == 16


def test_no_sprite_selected_means_dots(tmp_path):
    from processors.visualisation.embedding_map import EmbeddingMap

    processor = EmbeddingMap.__new__(EmbeddingMap)
    processor.parameters = {"thumbnails": ""}
    assert processor.load_sprite(["a.jpg"]) is None


def test_sprite_with_no_matching_items_falls_back_to_dots(tmp_path, monkeypatch):
    """The sheet may have been made from different media entirely."""
    from processors.visualisation import embedding_map as module

    sprite_dataset = make_sprite(tmp_path, ["a.jpg"], size=16, name="mismatch")
    monkeypatch.setattr(module, "DataSet", lambda **kwargs: sprite_dataset)

    processor = map_reading_sprite(tmp_path, sprite_dataset)
    assert processor.load_sprite(["totally-different.jpg"]) is None
    assert any("no tiles" in line for line in processor.dataset.logs)


# --------------------------------------------------------------------------- #
# individual thumbnails, so anything can use them - not just a tile blitter

def test_each_thumbnail_is_also_saved_on_its_own(tmp_path):
    import zipfile
    from processors.visualisation.media_thumbnails import MediaThumbnails

    dataset = make_sprite(tmp_path, ["a.jpg", "b.jpg", "c.jpg"], size=32, name="single")
    with zipfile.ZipFile(dataset.get_results_path()) as archive:
        members = archive.namelist()

    assert "sprite.jpg" in members and "index.json" in members
    assert len([m for m in members if m.startswith("thumbnails/")]) == 3

    sprite = MediaThumbnails.read_sprite(dataset)
    assert set(sprite["files"]) == {"a.jpg", "b.jpg", "c.jpg"}


def test_individual_thumbnails_are_real_images(tmp_path):
    import io
    import zipfile
    from PIL import Image
    from processors.visualisation.media_thumbnails import MediaThumbnails

    dataset = make_sprite(tmp_path, ["a.jpg", "b.jpg"], size=24, name="real")
    sprite = MediaThumbnails.read_sprite(dataset)

    with zipfile.ZipFile(dataset.get_results_path()) as archive:
        for member in sprite["files"].values():
            image = Image.open(io.BytesIO(archive.read(member)))
            assert image.format == "JPEG" and image.size == (24, 24)


def test_thumbnail_names_do_not_collide():
    """
    Everything becomes a JPEG, so `clip.mp4` and `clip.png` both want
    `clip.jpg`; the second must not silently overwrite the first.
    """
    from processors.visualisation.media_thumbnails import MediaThumbnails

    taken = {}
    taken["clip.png"] = "thumbnails/" + MediaThumbnails.thumbnail_name("clip.png", taken)
    taken["clip.mp4"] = "thumbnails/" + MediaThumbnails.thumbnail_name("clip.mp4", taken)
    taken["clip.gif"] = "thumbnails/" + MediaThumbnails.thumbnail_name("clip.gif", taken)

    assert len(set(taken.values())) == 3
    assert taken["clip.png"].endswith("clip.jpg")


# --------------------------------------------------------------------------- #
# clicking a thumbnail opens the media 4CAT already serves, permissions and all

def test_link_base_points_at_the_archive_download_route(tmp_path):
    from processors.visualisation.embedding_map import EmbeddingMap

    archive = FakeDataset(tmp_path, name="archivekey", dataset_type="video-downloader")
    embeddings = FakeDataset(tmp_path, name="emb", dataset_type="video-embeddings", parent=archive)

    class Config:
        def __init__(self, server=None, https=False):
            self.server, self.https = server, https

        def get(self, key, default=None):
            return {"flask.server_name": self.server, "flask.https": self.https}.get(key, default)

    processor = EmbeddingMap.__new__(EmbeddingMap)
    processor.source_dataset = FakeDataset(tmp_path, name="red", dataset_type="reduce-embeddings", parent=embeddings)

    # root-relative when the instance does not know its own hostname
    processor.config = Config()
    assert processor.media_link_base() == "/download/archivekey/?zip_member="

    # absolute otherwise, so a downloaded map still resolves
    processor.config = Config(server="4cat.example.org", https=True)
    assert processor.media_link_base() == "https://4cat.example.org/download/archivekey/?zip_member="


def test_no_link_base_without_an_archive(tmp_path):
    from processors.visualisation.embedding_map import EmbeddingMap

    processor = EmbeddingMap.__new__(EmbeddingMap)
    embeddings = FakeDataset(tmp_path, name="emb", dataset_type="text-embeddings")
    processor.source_dataset = FakeDataset(tmp_path, name="red", dataset_type="reduce-embeddings", parent=embeddings)
    assert processor.media_link_base() is None


def test_only_items_with_a_tile_get_a_link(tmp_path, monkeypatch):
    """A click should never open something the map is not showing."""
    from processors.visualisation import embedding_map as module

    sprite_dataset = make_sprite(tmp_path, ["a.jpg"], size=16, name="linked")
    monkeypatch.setattr(module, "DataSet", lambda **kwargs: sprite_dataset)

    processor = map_reading_sprite(tmp_path, sprite_dataset)
    result = processor.load_sprite(["a.jpg", "not-in-the-sheet.jpg"])

    assert result["files"] == ["a.jpg", ""]


# --------------------------------------------------------------------------- #
# the 3D plot: a 3D reduction as is, or a 2D one lifted by a column

class TopSource(Source):
    """A reduced dataset whose original dataset can be read for a column."""

    def __init__(self, items, parameters=None, top=None):
        super().__init__(items, parameters=parameters)
        self.top = top

    def top_parent(self):
        return self.top


def plot_3d(tmp_path, records, dimensions, top_items=(), **parameters):
    """Run the 3D plot over reduced records; return the processor."""
    from processors.visualisation.embedding_map_3d import EmbeddingMap3D

    processor = EmbeddingMap3D.__new__(EmbeddingMap3D)
    processor.dataset = FakeDataset(tmp_path, name="plot3d")
    processor.dataset.path = tmp_path / "plot3d.html"
    processor.source_dataset = TopSource([Item(record) for record in records],
                                         parameters={"dimensions": dimensions, "algorithm": "umap"},
                                         top=Source([Item(item) for item in top_items]))
    processor.interrupted = False
    processor.parameters = {"max_text_length": 100, "axis_column": "timestamp", "axis_spacing": "rank",
                            **parameters}
    processor.process()
    return processor


def read_payload(path):
    import json
    import re
    html = path.read_text(encoding="utf-8")
    return json.loads(re.search(r"var data = (.*?);\n", html).group(1))


def test_3d_plot_runs_on_two_and_three_dimensional_reductions(monkeypatch):
    from processors.visualisation import embedding_map_3d as module
    from processors.machine_learning.reduce_embeddings import ReduceEmbeddings

    monkeypatch.setattr(module, "DataSet", FakeDataset)
    for dimensions, expected in ((2, True), (3, True), (4, False), (1, False)):
        reduced = FakeDataset(Path("."), dataset_type="reduce-embeddings", parameters={"dimensions": dimensions})
        assert module.EmbeddingMap3D.is_compatible_with(reduced) is expected
    assert module.EmbeddingMap3D.is_compatible_with(ReduceEmbeddings) is True


def test_3d_plot_only_asks_for_a_column_when_it_needs_one(tmp_path):
    from processors.visualisation.embedding_map_3d import EmbeddingMap3D

    class Top(FakeDataset):
        def get_columns(self):
            return ["id", "body", "timestamp"]

    top = Top(tmp_path, name="top")
    flat = FakeDataset(tmp_path, name="flat", dataset_type="reduce-embeddings", parameters={"dimensions": 2})
    flat.top_parent = lambda: top
    options = EmbeddingMap3D.get_options(parent_dataset=flat, config=None)
    assert options["axis_column"]["type"] == "choice"
    assert options["axis_column"]["default"] == "timestamp"
    assert options["axis_spacing"]["default"] == "rank"

    cube = FakeDataset(tmp_path, name="cube", dataset_type="reduce-embeddings", parameters={"dimensions": 3})
    assert "axis_column" not in EmbeddingMap3D.get_options(parent_dataset=cube, config=None)


def test_3d_reduction_keeps_its_proportions(tmp_path):
    """Stretching each axis to fill the cube would distort the reduction."""
    records = [{"id": str(i), "text": f"t{i}", "coordinates": [i * 10.0, i * 1.0, 0.0]} for i in range(5)]
    processor = plot_3d(tmp_path, records, dimensions=3)
    assert processor.dataset.error is None, processor.dataset.error

    points = read_payload(processor.dataset.path)["points"]
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    assert max(xs) - min(xs) == pytest.approx(1.0)
    assert max(ys) - min(ys) == pytest.approx(0.1)


def test_2d_reduction_gets_its_height_from_the_original_dataset(tmp_path):
    records = [{"id": str(i), "text": f"t{i}", "coordinates": [float(i), float(i % 2)]} for i in range(4)]
    top = [{"id": str(i), "timestamp": f"2024-0{i + 1}-01 00:00:00"} for i in range(4)]

    processor = plot_3d(tmp_path, records, dimensions=2, top_items=top)
    assert processor.dataset.error is None, processor.dataset.error

    payload = read_payload(processor.dataset.path)
    assert [point[2] for point in payload["points"]] == pytest.approx([0, 1 / 3, 2 / 3, 1], abs=1e-4)
    assert payload["axis"]["title"] == "timestamp"
    assert "timestamp: 2024-01-01 00:00:00" in payload["labels"][0]


def test_media_posted_more_than_once_appears_once_per_post(tmp_path):
    records = [{"id": "img", "text": "img.jpg", "filename": "img.jpg", "post_ids": ["a", "b", "c"],
                "coordinates": [0.0, 0.0]},
               {"id": "other", "text": "other.jpg", "filename": "other.jpg", "post_ids": ["d"],
                "coordinates": [1.0, 1.0]}]
    top = [{"id": post_id, "timestamp": f"2024-01-0{day}"} for day, post_id in enumerate("abcd", start=1)]

    payload = read_payload(plot_3d(tmp_path, records, dimensions=2, top_items=top).dataset.path)
    # the same spot on the map, at three heights
    assert [point[:2] for point in payload["points"]][:3] == [[0.0, 0.0]] * 3
    assert len({point[2] for point in payload["points"][:3]}) == 3


def test_items_without_a_value_are_left_out_with_a_warning(tmp_path):
    records = [{"id": str(i), "text": f"t{i}", "coordinates": [float(i), float(i)]} for i in range(5)]
    top = [{"id": str(i), "timestamp": "" if i == 4 else f"2024-01-0{i + 1}"} for i in range(5)]

    processor = plot_3d(tmp_path, records, dimensions=2, top_items=top)
    assert processor.dataset.num_rows == 4
    assert any("no value" in message for message in processor.dataset.logs)


def test_a_column_nobody_has_is_an_error(tmp_path):
    records = [{"id": str(i), "text": "t", "coordinates": [float(i), 0.0]} for i in range(3)]
    processor = plot_3d(tmp_path, records, dimensions=2, top_items=[{"id": "0"}], axis_column="author")
    assert "author" in processor.dataset.error


@pytest.mark.parametrize("spacing", ["rank", "value"])
def test_a_text_column_can_be_the_height(tmp_path, spacing):
    """Author names and the like: subtracting them to place ticks used to crash."""
    records = [{"id": str(i), "text": f"t{i}", "coordinates": [float(i), float(i % 2)]} for i in range(4)]
    top = [{"id": str(i), "author": name} for i, name in enumerate(["bob", "Alice", "carol", "bob"])]

    processor = plot_3d(tmp_path, records, dimensions=2, top_items=top, axis_column="author", axis_spacing=spacing)
    assert processor.dataset.num_rows == 4

    payload = read_payload(processor.dataset.path)
    assert [point[2] for point in payload["points"]] == [0.5, 0.0, 1.0, 0.5]
    assert [tick[1] for tick in payload["axis"]["ticks"]] == ["Alice", "bob", "carol"]


def test_rank_spacing_gives_equal_values_one_height():
    from processors.visualisation.embedding_map_3d import EmbeddingMap3D

    axis = EmbeddingMap3D.build_axis(["2024-01-01", "2024-01-01", "2024-06-01", "2025-01-01"], "rank")
    assert axis["kind"] == "date"
    assert axis["positions"] == [0.0, 0.0, 0.5, 1.0]


def test_value_spacing_follows_the_values():
    from processors.visualisation.embedding_map_3d import EmbeddingMap3D

    axis = EmbeddingMap3D.build_axis([0, 1, 10], "value")
    assert axis["kind"] == "number"
    assert axis["positions"] == pytest.approx([0, 0.1, 1])
    assert [tick[0] for tick in axis["ticks"]] == pytest.approx([0, 0.2, 0.4, 0.6, 0.8, 1])


def test_text_columns_fall_back_to_rank():
    from processors.visualisation.embedding_map_3d import EmbeddingMap3D

    axis = EmbeddingMap3D.build_axis(["banana", "Apple", "cherry"], "value")
    assert axis["kind"] == "text" and axis["fallback"]
    # case does not decide the order
    assert axis["positions"] == [0.5, 0.0, 1.0]


@pytest.mark.parametrize("column,values,kind", [
    ("timestamp", [1700000000, 1710000000], "date"),
    ("unix_timestamp", ["1700000000", "1710000000"], "date"),
    ("likes", [1700000000, 1710000000], "number"),
    # small numbers are counts, whatever the column is called
    ("time_watched", [12, 300], "number"),
    ("weekday", ["may", "june"], "text"),
])
def test_value_kinds_are_recognised(column, values, kind):
    from processors.visualisation.embedding_map_3d import EmbeddingMap3D
    assert EmbeddingMap3D.parse_values(values, column)[0] == kind


def test_3d_plot_escapes_item_text(tmp_path):
    records = [{"id": str(i), "text": "</script><img src=x onerror=alert(1)>", "coordinates": [float(i), 0.0, 1.0]}
               for i in range(3)]
    html = plot_3d(tmp_path, records, dimensions=3).dataset.path.read_text(encoding="utf-8")
    assert "</script><img" not in html


# --------------------------------------------------------------------------- #
# clustering embeddings, and showing the clusters

def blobs(per_group=20, groups=3, dimensions=16, seed=3):
    """Embedding items in well-separated groups; group sizes shrink by 5."""
    import numpy as np
    rng = np.random.default_rng(seed)
    items, truth = [], []
    for group in range(groups):
        centre = np.zeros(dimensions)
        centre[group] = 10.0
        for _ in range(per_group - group * 5):
            items.append(Item({"id": str(len(items)), "text": f"group {group}",
                               "embedding": list(map(float, centre + rng.normal(0, 0.3, dimensions)))}))
            truth.append(group)
    return items, truth


def run_clustering(tmp_path, items, **parameters):
    """Cluster the given embedding items; return the processor."""
    from processors.machine_learning.cluster_embeddings import ClusterEmbeddings

    processor = ClusterEmbeddings.__new__(ClusterEmbeddings)
    processor.parameters = {"algorithm": "kmeans", "n_clusters": 3, "auto_clusters": False, "reduce_first": False,
                            "amount": 0, "save_annotations": False, **parameters}
    processor.dataset = FakeDataset(tmp_path, name="clustered")
    processor.dataset.path = tmp_path / "clustered.ndjson"
    processor.source_dataset, processor.interrupted = Source(items), False
    processor.saved_annotations = []
    processor.save_annotations = lambda annotations, **kwargs: processor.saved_annotations.extend(annotations)
    processor.process()
    return processor


def read_records(path):
    import json
    with path.open(encoding="utf-8") as infile:
        return [Item(json.loads(line)) for line in infile]


def same_grouping(found, truth):
    """Whether two labelings split the items the same way, whatever the numbers."""
    return len(set(zip(found, truth))) == len(set(truth)) == len(set(found))


def test_kmeans_finds_the_groups_and_numbers_them_by_size(tmp_path):
    items, truth = blobs()
    processor = run_clustering(tmp_path, items)
    assert processor.dataset.error is None, processor.dataset.error

    records = read_records(processor.dataset.path)
    clusters = [record["cluster"] for record in records]
    assert same_grouping(clusters, truth)
    # group 0 is the largest, so it is cluster 0
    assert clusters[0] == 0 and clusters[-1] == 2
    # the embeddings themselves pass through untouched
    assert records[0]["embedding"] == items[0]["embedding"]


def test_kmeans_can_choose_the_number_of_clusters(tmp_path):
    items, truth = blobs()
    processor = run_clustering(tmp_path, items, n_clusters=6, auto_clusters=True)
    clusters = [record["cluster"] for record in read_records(processor.dataset.path)]
    assert same_grouping(clusters, truth)
    assert any("Chose 3 clusters" in message for message in processor.dataset.logs)


def test_hdbscan_leaves_outliers_out(tmp_path):
    import numpy as np
    items, truth = blobs()
    # far from every group, and from each other
    for index in range(3):
        outlier = np.zeros(16)
        outlier[10 + index] = -40.0
        items.append(Item({"id": f"outlier{index}", "text": "outlier", "embedding": list(outlier)}))

    processor = run_clustering(tmp_path, items, algorithm="hdbscan", min_cluster_size=5)
    clusters = [record["cluster"] for record in read_records(processor.dataset.path)]
    assert clusters[-3:] == [-1, -1, -1]
    assert same_grouping(clusters[:-3], truth)


def test_hdbscan_min_samples_does_not_follow_min_cluster_size(tmp_path):
    from unittest.mock import patch
    import numpy as np

    items, _ = blobs()
    with patch("sklearn.cluster.HDBSCAN") as hdbscan:
        hdbscan.return_value.fit_predict.side_effect = lambda matrix: np.zeros(len(matrix), dtype=int)
        run_clustering(tmp_path, items, algorithm="hdbscan", min_cluster_size=20)

    # the default, not the cluster size: the neighbour search holds items x min_samples values
    assert hdbscan.call_args.kwargs["min_samples"] == 10
    assert hdbscan.call_args.kwargs["algorithm"] == "kd_tree"


def test_clustering_can_reduce_first(tmp_path):
    items, truth = blobs()
    processor = run_clustering(tmp_path, items, algorithm="hdbscan", min_cluster_size=5, reduce_first=True,
                               reduce_dimensions=3)
    assert processor.dataset.error is None, processor.dataset.error
    assert any("UMAP" in message for message in processor.dataset.logs)
    assert len(read_records(processor.dataset.path)) == len(items)


def test_clusters_are_annotated_once_per_post(tmp_path):
    items, _ = blobs(per_group=10, groups=2)
    items[0].update({"filename": "0.jpg", "post_ids": ["a", "b"]})

    processor = run_clustering(tmp_path, items, n_clusters=2, save_annotations=True)
    annotated = [annotation["item_id"] for annotation in processor.saved_annotations]
    # a media file stands for every post it appeared in; text for its own post
    assert annotated[:3] == ["a", "b", "1"]
    assert len(annotated) == len(items) + 1
    assert processor.saved_annotations[0]["label"] == "embedding cluster"


def test_media_without_post_ids_is_matched_through_the_archive(tmp_path):
    """
    Media embedded before post IDs were always recorded carry none. Their own
    ID is a file hash that matches no post, so annotating it writes nothing.
    """
    import json
    import zipfile

    items, _ = blobs(per_group=10, groups=2)
    for item in items:
        item.update({"filename": f"{item['id']}.jpg", "post_ids": []})

    archive = FakeDataset(tmp_path, name="archive", dataset_type="image-downloader")
    metadata = {"https://example.com/0": {"post_ids": ["p0", "p0b"], "files": [{"filename": "0.jpg"}]},
                "https://example.com/1": {"post_ids": ["p1"], "files": [{"filename": "1.jpg"}]}}
    with zipfile.ZipFile(archive.path, "w") as handle:
        handle.writestr(".metadata.json", json.dumps(metadata))

    from processors.machine_learning.cluster_embeddings import ClusterEmbeddings
    processor = ClusterEmbeddings.__new__(ClusterEmbeddings)
    processor.parameters = {"algorithm": "kmeans", "n_clusters": 2, "reduce_first": False, "amount": 0,
                            "save_annotations": True}
    processor.dataset = FakeDataset(tmp_path, name="clustered")
    processor.dataset.path = tmp_path / "clustered.ndjson"
    processor.source_dataset, processor.interrupted = Source(items, parent=archive), False
    processor.saved_annotations = []
    processor.save_annotations = lambda annotations, **kwargs: processor.saved_annotations.extend(annotations)
    processor.process()

    # only posts that exist are annotated; never a file hash
    assert [annotation["item_id"] for annotation in processor.saved_annotations] == ["p0", "p0b", "p1"]
    assert any(f"{len(items) - 2} files could not be linked" in message for message in processor.dataset.logs)


def test_clustered_embeddings_map_like_embeddings_plus_a_cluster():
    from processors.machine_learning.cluster_embeddings import ClusterEmbeddings

    row = ClusterEmbeddings.map_item({"id": "a", "text": "t", "embedding": [0.5, 1.0], "cluster": 2,
                                      "dimensions": 2}).get_item_data()
    assert row["cluster"] == 2 and row["embedding"] == "0.5 1.0"


def test_the_reducer_carries_the_cluster_along(tmp_path):
    items, _ = blobs(per_group=10, groups=2)
    for index, item in enumerate(items):
        item["cluster"] = index % 2

    records = read_reduced(run_reducer(tmp_path, items))
    assert [record["cluster"] for record in records] == [index % 2 for index in range(len(items))]

    from common.lib.item_mapping import MissingMappedField
    from processors.machine_learning.reduce_embeddings import ReduceEmbeddings
    assert ReduceEmbeddings.map_item(records[0]).get_item_data()["cluster"] == 0
    assert isinstance(ReduceEmbeddings.map_item({"id": "x", "coordinates": []}).data["cluster"], MissingMappedField)


def test_plots_look_past_the_clustering_for_thumbnails(tmp_path):
    """Thumbnails and media links hang off the archive, above the clustering."""
    from processors.visualisation.embedding_map import EmbeddingMap

    sprite = FakeDataset(tmp_path, name="sprite1", parameters={"thumbnail_size": 48}, rows=5)
    archive = FakeDataset(tmp_path, name="archive", children=[sprite])
    embeddings = FakeDataset(tmp_path, name="emb", dataset_type="image-embeddings", parent=archive)
    clustered = FakeDataset(tmp_path, name="clu", dataset_type="cluster-embeddings", parent=embeddings)
    reduced = FakeDataset(tmp_path, name="red", dataset_type="reduce-embeddings", parent=clustered)

    assert EmbeddingMap.get_embeddings_dataset(reduced) is embeddings
    assert list(EmbeddingMap.find_sprite_datasets(reduced)) == ["sprite1"]
    assert EmbeddingMap.has_clusters(reduced)
    assert "colour_clusters" in EmbeddingMap.get_options(parent_dataset=reduced, config=None)

    plain = FakeDataset(tmp_path, name="red2", dataset_type="reduce-embeddings", parent=embeddings)
    assert not EmbeddingMap.has_clusters(plain)
    assert "colour_clusters" not in EmbeddingMap.get_options(parent_dataset=plain, config=None)


def test_cluster_colours_stay_fixed_and_do_not_cycle():
    from processors.visualisation.embedding_map import CLUSTER_PALETTE, EmbeddingMap

    clusters = [0, 0, 1, 7, 8, 9, 9, -1]
    colours = EmbeddingMap.cluster_colours(clusters)
    others, noise = len(CLUSTER_PALETTE), len(CLUSTER_PALETTE) + 1

    assert colours["colour"] == [0, 0, 1, 7, others, others, others, noise]
    labels = [entry[0] for entry in colours["legend"]]
    assert labels == ["Cluster 0 (2)", "Cluster 1 (1)", "Cluster 7 (1)", "2 smaller clusters (3)", "No cluster (1)"]


def test_the_map_colours_by_cluster_when_it_can(tmp_path):
    from processors.visualisation.embedding_map import EmbeddingMap

    records = [Item({"id": str(i), "text": f"t{i}", "coordinates": [float(i), float(i % 3)], "cluster": i % 2 - 1})
               for i in range(6)]

    def render(**parameters):
        processor = EmbeddingMap.__new__(EmbeddingMap)
        processor.dataset = Collector(tmp_path / "map.html")
        processor.source_dataset = Source(records, parameters={"algorithm": "umap"})
        processor.interrupted = False
        processor.parameters = {"max_text_length": 100, **parameters}
        processor.process()
        return read_payload(processor.dataset.path)

    payload = render()
    assert payload["colour"][:2] == [len(payload["palette"]) - 1, 0]
    assert payload["labels"][0].endswith("No cluster") and payload["labels"][1].endswith("Cluster 0")
    assert "colour" not in render(colour_clusters=False)


def test_the_3d_plot_keeps_clusters_in_step_with_repeated_points(tmp_path):
    """A media file posted twice is two points, both in the file's cluster."""
    records = [{"id": "img", "text": "img.jpg", "filename": "img.jpg", "post_ids": ["a", "b"], "cluster": 1,
                "coordinates": [0.0, 0.0]},
               {"id": "other", "text": "other.jpg", "filename": "other.jpg", "post_ids": ["c"], "cluster": 0,
                "coordinates": [1.0, 1.0]},
               {"id": "third", "text": "third.jpg", "filename": "third.jpg", "post_ids": ["d"], "cluster": -1,
                "coordinates": [0.5, 1.0]}]
    top = [{"id": post_id, "timestamp": f"2024-01-0{day}"} for day, post_id in enumerate("abcd", start=1)]

    payload = read_payload(plot_3d(tmp_path, records, dimensions=2, top_items=top).dataset.path)
    assert payload["colour"][:3] == [1, 1, 0]
    assert payload["labels"][0].endswith("Cluster 1")
    # the height axis keeps its ticks; only the colours come from the clusters
    assert payload["axis"]["title"] == "timestamp"


def test_3d_plot_links_media_to_posts_through_the_archive(tmp_path):
    """
    top dataset -> video archive -> video embeddings -> clusters -> reduction:
    embeddings made before post IDs were always recorded have none, and their
    own ID is a file hash, so the posts come from the archive's metadata.
    """
    import json
    import zipfile
    from processors.visualisation.embedding_map_3d import EmbeddingMap3D

    archive = FakeDataset(tmp_path, name="archive", dataset_type="video-downloader")
    metadata = {f"https://example.com/{name}": {"post_ids": posts, "files": [{"filename": f"{name}.mp4"}]}
                for name, posts in (("v1", ["p1"]), ("v2", ["p2", "p3"]), ("v3", ["p4"]))}
    with zipfile.ZipFile(archive.path, "w") as handle:
        handle.writestr(".metadata.json", json.dumps(metadata))
    embeddings = FakeDataset(tmp_path, name="emb", dataset_type="video-embeddings", parent=archive)
    clustered = FakeDataset(tmp_path, name="clu", dataset_type="cluster-embeddings", parent=embeddings)

    records = [Item({"id": name, "text": f"{name}.mp4", "filename": f"{name}.mp4", "post_ids": [], "cluster": 0,
                     "coordinates": [float(index), float(index % 2)]})
               for index, name in enumerate(("v1", "v2", "v3", "unknown"))]
    top = Source([Item({"id": f"p{index}", "likes": index * 10}) for index in range(1, 5)])

    processor = EmbeddingMap3D.__new__(EmbeddingMap3D)
    processor.dataset = FakeDataset(tmp_path, name="plot3d")
    processor.dataset.path = tmp_path / "plot3d.html"
    processor.source_dataset = TopSource(records, parameters={"dimensions": 2, "algorithm": "umap"}, top=top)
    processor.source_dataset._parent = clustered
    processor.interrupted = False
    processor.parameters = {"max_text_length": 100, "axis_column": "likes", "axis_spacing": "value"}
    processor.process()

    assert processor.dataset.error is None, processor.dataset.error
    payload = read_payload(processor.dataset.path)
    # v2 was posted twice, so it appears twice; the unknown file is left out
    assert [label.split("\n")[1] for label in payload["labels"]] == ["likes: 10", "likes: 20", "likes: 30",
                                                                    "likes: 40"]
    assert any("1 files could not be linked" in message for message in processor.dataset.logs)


def test_3d_plot_says_so_when_no_media_can_be_linked(tmp_path):
    records = [{"id": f"v{index}", "text": "v.mp4", "filename": "v.mp4", "post_ids": [],
                "coordinates": [float(index), 0.0]} for index in range(3)]
    processor = plot_3d(tmp_path, records, dimensions=2, top_items=[{"id": "p1", "timestamp": "2024-01-01"}])
    assert "could be linked to a post" in processor.dataset.error


# --------------------------------------------------------------------------- #
# failed files: a long run should survive the odd bad file, and keep its work

class ScriptedClient:
    """Embeds or fails each file in turn, following a script of True/False."""

    def __init__(self, script, attempts=3):
        self.script, self.attempts = list(script), attempts
        self.file, self.tries = 0, 0

    def embed(self, model_id, inputs, media=None, text_as_instruction=False):
        from common.lib.exceptions import LLMServerException
        succeeds = self.script[self.file]
        if succeeds:
            self.file, self.tries = self.file + 1, 0
            return [[0.1, 0.2]]

        self.tries += 1
        if self.tries == self.attempts:
            self.file, self.tries = self.file + 1, 0
        raise LLMServerException("Server returned status 400: Failed to apply Qwen3VLProcessor")


def run_media_embedder(tmp_path, monkeypatch, script):
    """Embed one small image per script entry; return the processor."""
    from PIL import Image
    from processors.machine_learning import embed_media

    monkeypatch.setattr(embed_media.time, "sleep", lambda seconds: None)

    media = tmp_path / "images"
    media.mkdir()

    class MediaItem:
        def __init__(self, file):
            self.file = file

    items = []
    for index in range(len(script)):
        path = media / f"img{index:03d}.jpg"
        Image.new("RGB", (40, 30), (index % 255, 80, 120)).save(path)
        items.append(MediaItem(path))

    class Archive:
        num_rows = len(items)

        def iterate_items(self, processor=None, **kwargs):
            return iter(items)

    class Output(FakeDataset):
        def finish_with_warning(self, rows, warning):
            self.num_rows, self.warning = rows, warning

    processor = EmbedImages.__new__(EmbedImages)
    processor.dataset = Output(tmp_path, name="embeddings")
    processor.dataset.path, processor.dataset.warning = tmp_path / "embeddings.ndjson", None
    processor.source_dataset, processor.source_file, processor.interrupted = Archive(), None, False
    processor.parameters = {"model": "m", "instruction": "", "amount": 0, "max_size": 64}
    processor.resolve_model = lambda: ({"local_id": "m"}, ScriptedClient(script))
    processor.save_annotations = lambda *args, **kwargs: None
    processor.process()
    return processor


def test_scattered_failures_do_not_stop_a_run(tmp_path, monkeypatch):
    """More failures in total than the limit, but never many in a row."""
    script = ([True, True, False] * 15)[:45]
    processor = run_media_embedder(tmp_path, monkeypatch, script)

    assert processor.dataset.error is None
    assert processor.dataset.num_rows == 30
    assert "15 images could not be embedded" in processor.dataset.warning
    assert "Stopped" not in processor.dataset.warning


def test_failures_in_a_row_stop_but_keep_what_was_embedded(tmp_path, monkeypatch):
    """A server that goes down fails every file; the work before that is kept."""
    script = [True] * 5 + [False] + [True] + [False] * 12
    processor = run_media_embedder(tmp_path, monkeypatch, script)

    # finished with a warning, not an error, and with the vectors it made
    assert processor.dataset.error is None
    assert processor.dataset.num_rows == 6
    assert "Stopped after 10 images in a row" in processor.dataset.warning
    assert "11 images could not be embedded in total" in processor.dataset.warning
    with processor.dataset.path.open(encoding="utf-8") as infile:
        assert len(infile.readlines()) == 6


def test_failing_from_the_start_is_still_an_error(tmp_path, monkeypatch):
    processor = run_media_embedder(tmp_path, monkeypatch, [False] * 12)
    assert "Stopped after 10 images in a row" in processor.dataset.error
    assert processor.dataset.num_rows == 0


# --------------------------------------------------------------------------- #
# sizing points by a column

def test_sizes_scale_between_the_bounds_and_fill_gaps_with_the_median():
    from processors.visualisation.embedding_map import SIZE_RANGE, EmbeddingMap

    linear = EmbeddingMap.size_factors([0, 50, 100, "n/a"], "linear")
    assert linear[0] == SIZE_RANGE[0] and linear[2] == SIZE_RANGE[1]
    # not a number: counts as the median of the numbers, 50
    assert linear[3] == linear[1] == pytest.approx(sum(SIZE_RANGE) / 2)

    # on a log scale, ordinary values are not all squashed to the minimum
    views = [10, 100, 1000, 1_000_000]
    assert EmbeddingMap.size_factors(views, "log")[1] > EmbeddingMap.size_factors(views, "linear")[1] + 0.3
    assert EmbeddingMap.size_factors(["a", None], "log") is None


def test_the_map_sizes_a_reposted_file_by_its_largest_post(tmp_path):
    from processors.visualisation.embedding_map import EmbeddingMap

    records = [Item({"id": "v1", "text": "v1.mp4", "filename": "v1.mp4", "post_ids": ["a", "b"],
                     "coordinates": [0.0, 0.0]}),
               Item({"id": "v2", "text": "v2.mp4", "filename": "v2.mp4", "post_ids": ["c"],
                     "coordinates": [1.0, 1.0]}),
               Item({"id": "v3", "text": "v3.mp4", "filename": "v3.mp4", "post_ids": ["d"],
                     "coordinates": [0.5, 0.2]})]
    top = Source([Item({"id": post_id, "views": views}) for post_id, views in
                  (("a", 10), ("b", 1000), ("c", 100), ("d", 10))])

    processor = EmbeddingMap.__new__(EmbeddingMap)
    processor.dataset = Collector(tmp_path / "map.html")
    processor.dataset.log = lambda message: None
    processor.source_dataset = TopSource(records, parameters={"algorithm": "umap"}, top=top)
    processor.interrupted = False
    processor.parameters = {"max_text_length": 100, "size_column": "views", "size_scale": "linear"}
    processor.process()

    sizes = read_payload(processor.dataset.path)["sizes"]
    # v1's largest post has the most views of all
    assert sizes[0] == max(sizes) and sizes[2] == min(sizes)


# --------------------------------------------------------------------------- #
# embedding streams: distance to a reference over time

def stream_items(per_cluster=6, clusters=(0, 1), drift=0.0):
    """
    Clustered text embeddings, one post per day. Cluster c points along axis c,
    and drifts towards the next axis by `drift` per day.
    """
    items, top = [], []
    for cluster in clusters:
        for day in range(per_cluster):
            vector = [0.0] * 4
            vector[cluster] = 1.0
            vector[cluster + 2] = drift * day
            post_id = f"p{cluster}-{day}"
            items.append(Item({"id": post_id, "text": f"cluster {cluster} day {day}", "cluster": cluster,
                               "embedding": vector}))
            top.append(Item({"id": post_id, "timestamp": f"2024-01-{day + 1:02d} 12:00:00",
                             "original_sound": "yes" if day % 2 else "no", "views": 10 ** day}))
    return items, top


def run_streams(tmp_path, items, top, source_type="cluster-embeddings", **parameters):
    """Run the streams plot; return the processor and its payload (or None on error)."""
    from processors.visualisation.embedding_streams import EmbeddingStreams

    class Output(FakeDataset):
        def finish_with_warning(self, rows, warning):
            self.num_rows, self.warning = rows, warning

    processor = EmbeddingStreams.__new__(EmbeddingStreams)
    processor.dataset = Output(tmp_path, name="streams")
    processor.dataset.path, processor.dataset.warning = tmp_path / "streams.html", None
    processor.source_dataset = TopSource(items, top=Source(top))
    processor.source_dataset.type = source_type
    processor.interrupted, processor.config, processor.log = False, None, None
    processor.parameters = {"max_text_length": 100, "time_column": "timestamp", "time_window": "day",
                            "reference": "centre", "split": "alternate", "trend_lines": True,
                            # the form's default for clustered embeddings
                            "use_clusters": True, **parameters}
    processor.process()
    payload = read_payload(processor.dataset.path) if processor.dataset.error is None else None
    return processor, payload


def test_streams_run_on_embeddings_and_clustered_embeddings():
    from processors.visualisation.embedding_streams import EmbeddingStreams
    from processors.machine_learning.reduce_embeddings import ReduceEmbeddings

    for dataset_type in ("text-embeddings", "image-embeddings", "video-embeddings", "cluster-embeddings"):
        assert EmbeddingStreams.is_compatible_with(FakeDataset(Path("."), dataset_type=dataset_type))
    assert not EmbeddingStreams.is_compatible_with(FakeDataset(Path("."), dataset_type="reduce-embeddings"))
    assert not EmbeddingStreams.is_compatible_with(ReduceEmbeddings)


def test_streams_measure_each_cluster_against_its_own_centre(tmp_path):
    items, top = stream_items()
    processor, payload = run_streams(tmp_path, items, top)
    assert processor.dataset.error is None, processor.dataset.error

    # without drift, every item sits on its cluster's centre
    assert all(point[1] == pytest.approx(0, abs=1e-5) for point in payload["points"])
    # points are in time order, and each cluster alternates between the halves
    # on its own, so no cluster ends up in one half
    clusters = [label.rsplit("Cluster ", 1)[1] for label in payload["labels"]]
    for cluster in ("0", "1"):
        sides = [point[2] for point, label in zip(payload["points"], clusters) if label == cluster]
        assert sides == [1, -1] * 3
    # one trend line per cluster and half
    assert len(payload["trend"]) == 4
    assert {line["colour"] for line in payload["trend"]} == {"#2a78d6", "#eb6834"}


def test_drift_shows_as_growing_distance_from_the_first_window(tmp_path):
    items, top = stream_items(drift=0.5)
    processor, payload = run_streams(tmp_path, items, top, reference="first_window", clusters="0")

    distances = [point[1] for point in payload["points"]]
    assert len(distances) == 6
    assert distances[0] == pytest.approx(0, abs=1e-5)
    assert distances == sorted(distances)


def test_the_previous_window_leaves_out_each_clusters_first_window(tmp_path):
    items, top = stream_items(drift=0.5)
    processor, payload = run_streams(tmp_path, items, top, reference="previous_window")

    # one first window per cluster has nothing before it
    assert len(payload["points"]) == 10
    assert "2 items in each cluster's first time window" in processor.dataset.warning


def test_the_medoid_is_marked(tmp_path):
    items, top = stream_items(drift=0.5)
    processor, payload = run_streams(tmp_path, items, top, reference="medoid", clusters="1")

    assert len(payload["marked"]) == 1 and payload["markedLabel"] == "medoid"
    marked = payload["marked"][0]
    assert payload["points"][marked][1] == pytest.approx(0, abs=1e-5)
    assert payload["labels"][marked].endswith("(this cluster's medoid)")


def test_distance_to_a_text_prompt(tmp_path, monkeypatch):
    import numpy as np
    from processors.visualisation import embedding_streams as module

    monkeypatch.setattr(module, "embed_query", lambda *args, **kwargs: (np.asarray([1.0, 0, 0, 0]), {}, None))
    items, top = stream_items()
    processor, payload = run_streams(tmp_path, items, top, reference="text", reference_text="cats")

    distances = sorted({round(point[1], 4) for point in payload["points"]})
    # cluster 0 points the same way as the prompt; cluster 1 is orthogonal
    assert distances == [0.0, 1.0]
    assert "text prompt 'cats'" in payload["reference"]


def test_distance_to_an_item_found_by_its_post_id(tmp_path):
    items, top = stream_items(drift=0.5)
    processor, payload = run_streams(tmp_path, items, top, reference="item", reference_item="p1-3")

    assert payload["markedLabel"] == "reference" and len(payload["marked"]) == 1
    assert payload["points"][payload["marked"][0]][1] == pytest.approx(0, abs=1e-5)

    processor, payload = run_streams(tmp_path, items, top, reference="item", reference_item="nope")
    assert "nope" in processor.dataset.error


def test_a_yes_no_column_decides_the_half(tmp_path):
    from processors.visualisation.embedding_streams import EmbeddingStreams

    for value in ("true", "Yes", "x", "1", "anything"):
        assert EmbeddingStreams.is_true(value), value
    for value in ("false", "NO", "0", "0.0", "", None, False):
        assert not EmbeddingStreams.is_true(value), value

    items, top = stream_items()
    processor, payload = run_streams(tmp_path, items, top, split="column", split_column="original_sound",
                                     clusters="0")
    # odd days have an original sound
    assert [point[2] for point in payload["points"]] == [-1, 1, -1, 1, -1, 1]
    assert payload["halves"] == {"top": "original_sound: yes", "bottom": "original_sound: no"}


def test_streams_can_be_sized_by_a_column(tmp_path):
    items, top = stream_items()
    processor, payload = run_streams(tmp_path, items, top, size_column="views", size_scale="log", clusters="0")
    assert payload["sizes"] == sorted(payload["sizes"])


def test_time_windows_slice_by_calendar_unit():
    import datetime
    from processors.visualisation.embedding_streams import EmbeddingStreams

    def at(text):
        return datetime.datetime.fromisoformat(text).replace(tzinfo=datetime.timezone.utc).timestamp()

    window = EmbeddingStreams.window_of
    assert window(at("2024-01-31 23:00"), "month") != window(at("2024-02-01 00:00"), "month")
    assert window(at("2024-01-01 00:00"), "year") == window(at("2024-12-31 23:59"), "year")
    assert window(at("2024-01-01 10:59"), "hour") == window(at("2024-01-01 10:00"), "hour")
    assert window(at("2024-01-01 23:59"), "day") != window(at("2024-01-02 00:00"), "day")


def test_clusters_to_include_must_be_numbers():
    from common.lib.exceptions import QueryParametersException
    from processors.visualisation.embedding_streams import EmbeddingStreams

    assert EmbeddingStreams.parse_clusters("0, 2,-1") == {0, 2, -1}
    assert EmbeddingStreams.parse_clusters("") is None
    with pytest.raises(QueryParametersException):
        EmbeddingStreams.validate_query({"clusters": "0, two"}, None, None)
    with pytest.raises(QueryParametersException):
        EmbeddingStreams.validate_query({"reference": "text", "reference_text": " "}, None, None)


def test_streams_need_dates(tmp_path):
    items, top = stream_items()
    for row in top:
        row["timestamp"] = "not a date"
    processor, payload = run_streams(tmp_path, items, top)
    assert "does not hold dates" in processor.dataset.error


def test_time_ticks_sit_at_window_starts():
    import datetime
    from processors.visualisation.embedding_streams import EmbeddingStreams

    def at(text):
        return datetime.datetime.fromisoformat(text).replace(tzinfo=datetime.timezone.utc).timestamp()

    for unit, moment in (("day", "2024-03-05 00:00"), ("month", "2024-03-01 00:00"), ("year", "2024-01-01 00:00"),
                         ("hour", "2024-03-05 13:00")):
        window = EmbeddingStreams.window_of(at(moment), unit)
        assert EmbeddingStreams.window_start(window, unit) == at(moment), unit

    times = [at("2024-03-01 10:00"), at("2024-03-07 18:00")]
    ticks = EmbeddingStreams.window_ticks(times, "day")
    # every midnight within the range, none skipped
    assert [label for _, label in ticks] == [f"2024-03-0{day}" for day in range(2, 8)]
    assert all(0 <= position <= 1 for position, _ in ticks)


# --------------------------------------------------------------------------- #
# reading embeddings without holding them twice

def embeddings_dataset(records):
    """An embeddings dataset that yields the given records."""
    return Source([Item(record) for record in records], dataset_type="text-embeddings")


def test_vectors_are_read_into_one_float32_array(tmp_path):
    from common.lib.embeddings import read_embedding_matrix

    records = [{"id": "a", "embedding": [1.0, 2.0, 3.0]},
               {"id": "b", "embedding": []},
               {"id": "c", "embedding": [4.0, 5.0, 6.0]},
               {"id": "d", "embedding": [7.0, 8.0, 9.0]}]
    matrix, positions, kept = read_embedding_matrix(embeddings_dataset(records), limit=10)

    assert matrix.dtype.name == "float32" and matrix.shape == (3, 3)
    # the record without a vector is skipped, and the positions say where each row came from
    assert positions == [0, 2, 3] and kept == []
    assert matrix[1].tolist() == [4.0, 5.0, 6.0]

    matrix, positions, _ = read_embedding_matrix(embeddings_dataset(records), limit=2)
    assert positions == [0, 2]


def test_reading_can_filter_and_keep_a_summary():
    from common.lib.embeddings import read_embedding_matrix

    records = [{"id": str(i), "cluster": i % 2, "embedding": [float(i), 1.0]} for i in range(6)]
    matrix, positions, kept = read_embedding_matrix(embeddings_dataset(records), limit=6,
                                                    accept=lambda record: record["cluster"] == 1,
                                                    keep=lambda record: record["id"])
    assert positions == [1, 3, 5] and kept == ["1", "3", "5"]
    assert matrix[:, 0].tolist() == [1.0, 3.0, 5.0]


def test_an_item_is_found_with_its_vector():
    from common.lib.embeddings import find_embedding

    records = [{"id": "a", "embedding": [1.0, 0.0]}, {"id": "b", "embedding": [0.0, 1.0]}]
    vector, record = find_embedding(embeddings_dataset(records), lambda record: record["id"] == "b")
    assert record["id"] == "b" and vector.tolist() == [0.0, 1.0]
    assert find_embedding(embeddings_dataset(records), lambda record: False) == (None, None)


def test_mixed_vector_sizes_are_refused(tmp_path):
    from common.lib.embeddings import read_embedding_matrix

    records = [{"id": "a", "embedding": [1.0, 2.0]}, {"id": "b", "embedding": [1.0, 2.0, 3.0]}]
    with pytest.raises(ValueError):
        read_embedding_matrix(embeddings_dataset(records), limit=10)


def test_normalising_happens_in_place():
    import numpy as np
    from common.lib.embeddings import normalise_in_place

    matrix = np.asarray([[3.0, 4.0], [0.0, 0.0]], dtype=np.float32)
    result = normalise_in_place(matrix)
    assert result is matrix
    assert matrix[0].tolist() == pytest.approx([0.6, 0.8]) and matrix[1].tolist() == [0.0, 0.0]


def test_clustering_writes_records_back_unchanged_but_for_the_cluster(tmp_path):
    items, _ = blobs(per_group=10, groups=2)
    for item in items:
        item.update({"model": "m", "extra": {"nested": [1, 2]}, "text": "naïve 🎉"})

    processor = run_clustering(tmp_path, items, n_clusters=2)
    records = read_records(processor.dataset.path)
    assert len(records) == len(items)
    for item, record in zip(items, records):
        cluster = record.pop("cluster")
        assert cluster in (0, 1)
        assert dict(record) == dict(item)


def test_cluster_annotations_are_saved_in_batches(tmp_path):
    from processors.machine_learning.cluster_embeddings import ClusterEmbeddings

    items, _ = blobs(per_group=15, groups=2)
    batches = []

    processor = ClusterEmbeddings.__new__(ClusterEmbeddings)
    processor.annotation_batch_size = 7
    processor.parameters = {"algorithm": "kmeans", "n_clusters": 2, "reduce_first": False, "amount": 0,
                            "save_annotations": True}
    processor.dataset = FakeDataset(tmp_path, name="clustered")
    processor.dataset.path = tmp_path / "clustered.ndjson"
    processor.source_dataset = Source(items)
    processor.interrupted = False
    processor.save_annotations = lambda annotations, **kwargs: batches.append(list(annotations))
    processor.process()

    # 25 items: three full batches of 7 while writing, then the remaining 4
    assert [len(batch) for batch in batches] == [7, 7, 7, 4]
    assert sorted(annotation["item_id"] for batch in batches for annotation in batch) == \
        sorted(item["id"] for item in items)


def test_without_use_clusters_all_items_are_one_stream(tmp_path):
    items, top = stream_items()
    # the filter only applies with 'Use clusters', so it is ignored here
    processor, payload = run_streams(tmp_path, items, top, use_clusters=False, clusters="0")

    assert len(payload["points"]) == 12
    # one shared centre: the clusters sit on either side of it, not on it
    assert all(point[1] > 0.1 for point in payload["points"])
    # one trend line per half, in the default colour
    assert len(payload["trend"]) == 2
    assert {line["colour"] for line in payload["trend"]} == {"#285ca8"}
    assert ", per cluster" not in payload["reference"]
    # the points can still be coloured by their cluster
    assert "colour" in payload


def test_use_clusters_is_only_offered_for_clustered_embeddings(tmp_path):
    from processors.visualisation.embedding_streams import EmbeddingStreams

    clustered = FakeDataset(tmp_path, name="clu", dataset_type="cluster-embeddings")
    options = EmbeddingStreams.get_options(parent_dataset=clustered, config=None)
    assert options["use_clusters"]["default"] is True
    assert options["clusters"]["requires"] == "use_clusters==true"

    plain = FakeDataset(tmp_path, name="emb", dataset_type="text-embeddings")
    options = EmbeddingStreams.get_options(parent_dataset=plain, config=None)
    assert "use_clusters" not in options and "clusters" not in options
