"""
Tests for the media-embedding processors:

- `processors/machine_learning/embed_media.py` — the shared base, which must
  stay abstract so it is never registered as a processor in its own right.
- `embed_videos.py` / `embed_images.py` — that both keep the same option shape
  and wording, and that media-specific behaviour stays media-specific.

These import the processor classes directly and never touch a server.
"""
import inspect

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

def build_map(tmp_path, texts, algorithm="pca"):
    """Render a map for the given hover texts and return the HTML."""
    from processors.visualisation.embedding_map import EmbeddingMap

    class Dataset:
        def __init__(self):
            self.path, self.error, self.rows, self.key = tmp_path / "map.html", None, 0, "testkey"

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
        def __init__(self, items):
            self.items = items

        @property
        def num_rows(self):
            return len(self.items)

        def iterate_items(self, processor=None, **kwargs):
            return iter(self.items)

    items = [{"id": i, "text": text, "embedding": [float((i * 7 + j) % 11) for j in range(8)]}
             for i, text in enumerate(texts)]

    processor = EmbeddingMap.__new__(EmbeddingMap)
    processor.dataset, processor.source_dataset, processor.interrupted = Dataset(), Source(items), False
    processor.parameters = {"algorithm": algorithm, "amount": 0, "max_text_length": 100}
    processor.process()

    assert processor.dataset.error is None, processor.dataset.error
    return processor.dataset.path


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

def test_map_accepts_every_embedding_type():
    """Image embeddings were missing, which is where thumbnails matter most."""
    from processors.visualisation.embedding_map import EmbeddingMap

    assert EmbeddingMap.compatibility.types == {"text-embeddings", "video-embeddings", "image-embeddings"}


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

    found = EmbeddingMap.find_sprite_datasets(embeddings)
    assert list(found) == ["sprite1"], "only finished sprite sheets should be offered"
    assert "48px" in found["sprite1"] and "120" in found["sprite1"]


@pytest.mark.parametrize("dataset_type", ["text-embeddings", "tokenise-posts"])
def test_map_offers_no_sprites_for_non_media(tmp_path, dataset_type):
    from processors.visualisation.embedding_map import EmbeddingMap

    sprite = FakeDataset(tmp_path, name="sprite1", parameters={"thumbnail_size": 48}, rows=5)
    archive = FakeDataset(tmp_path, name="archive", children=[sprite])
    parent = FakeDataset(tmp_path, name="p", dataset_type=dataset_type, parent=archive)

    assert EmbeddingMap.find_sprite_datasets(parent) == {}
    assert EmbeddingMap.find_sprite_datasets(None) == {}


def test_map_option_is_a_picker_when_sprites_exist(tmp_path):
    from processors.visualisation.embedding_map import EmbeddingMap

    sprite = FakeDataset(tmp_path, name="sprite1", parameters={"thumbnail_size": 48}, rows=9)
    archive = FakeDataset(tmp_path, name="archive", children=[sprite])
    embeddings = FakeDataset(tmp_path, name="emb", dataset_type="image-embeddings", parent=archive)

    options = EmbeddingMap.get_options(parent_dataset=embeddings, config=None)
    assert options["thumbnails"]["type"] == "choice"
    # "no thumbnails" has to stay available, and be the default
    assert options["thumbnails"]["default"] == ""
    assert "sprite1" in options["thumbnails"]["options"]


def test_map_explains_how_to_get_thumbnails_when_there_are_none(tmp_path):
    """Otherwise the option is simply absent and nobody knows it exists."""
    from processors.visualisation.embedding_map import EmbeddingMap

    archive = FakeDataset(tmp_path, name="archive", children=[])
    embeddings = FakeDataset(tmp_path, name="emb", dataset_type="video-embeddings", parent=archive)

    options = EmbeddingMap.get_options(parent_dataset=embeddings, config=None)
    assert "thumbnails" not in options
    assert "Extract thumbnails" in options["thumbnails_info"]["help"]


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
    processor.source_dataset = embeddings

    # root-relative when the instance does not know its own hostname
    processor.config = Config()
    assert processor.media_link_base() == "/download/archivekey/?zip_member="

    # absolute otherwise, so a downloaded map still resolves
    processor.config = Config(server="4cat.example.org", https=True)
    assert processor.media_link_base() == "https://4cat.example.org/download/archivekey/?zip_member="


def test_no_link_base_without_an_archive(tmp_path):
    from processors.visualisation.embedding_map import EmbeddingMap

    processor = EmbeddingMap.__new__(EmbeddingMap)
    processor.source_dataset = FakeDataset(tmp_path, name="emb", dataset_type="text-embeddings")
    assert processor.media_link_base() is None


def test_only_items_with_a_tile_get_a_link(tmp_path, monkeypatch):
    """A click should never open something the map is not showing."""
    from processors.visualisation import embedding_map as module

    sprite_dataset = make_sprite(tmp_path, ["a.jpg"], size=16, name="linked")
    monkeypatch.setattr(module, "DataSet", lambda **kwargs: sprite_dataset)

    processor = map_reading_sprite(tmp_path, sprite_dataset)
    result = processor.load_sprite(["a.jpg", "not-in-the-sheet.jpg"])

    assert result["files"] == ["a.jpg", ""]
