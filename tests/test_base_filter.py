"""
Tests for filtering archive datasets with `BaseFilter`
"""
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.lib.processor import BasicProcessor
from processors.filtering.base_filter import BaseFilter


def run_filter(tmp_path, archive_contents):
    """
    Filter an archive dataset, keeping its one image

    :return tuple:  The staging area the filter wrote to, and the mocked
      `write_archive_and_finish`
    """
    source_archive = tmp_path / "source.zip"
    with zipfile.ZipFile(source_archive, "w") as archive:
        for filename in archive_contents:
            archive.writestr(filename, "content")

    image = tmp_path / "a.jpg"
    image.write_text("content")
    staging_area = tmp_path / "staging"
    staging_area.mkdir()

    processor = MagicMock()
    processor.source_dataset.get_extension.return_value = "zip"
    processor.source_dataset.get_results_path.return_value = source_archive
    processor.source_dataset.num_annotations.return_value = 0
    processor.dataset.get_results_path.return_value = tmp_path / "results.zip"
    processor.dataset.get_staging_area.return_value = staging_area
    processor.dataset.is_finished.return_value = False
    processor.filter_items.return_value = [SimpleNamespace(original={"id": "a.jpg"}, file=image)]
    processor.extract_archived_file_by_name = lambda *args: BasicProcessor.extract_archived_file_by_name(processor, *args)

    BaseFilter.process(processor)
    return staging_area, processor.write_archive_and_finish


def test_filter_archive_without_metadata(tmp_path):
    """An archive without .metadata.json (e.g. uploaded media) can be filtered"""
    staging_area, write_archive_and_finish = run_filter(tmp_path, ["a.jpg"])

    assert sorted(file.name for file in staging_area.iterdir()) == ["a.jpg"]
    write_archive_and_finish.assert_called_once_with(staging_area, 1)


def test_filter_archive_keeps_metadata(tmp_path):
    staging_area, write_archive_and_finish = run_filter(tmp_path, [".metadata.json", "a.jpg"])

    assert sorted(file.name for file in staging_area.iterdir()) == [".metadata.json", "a.jpg"]
    write_archive_and_finish.assert_called_once_with(staging_area, 1)
