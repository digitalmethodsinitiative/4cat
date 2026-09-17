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
