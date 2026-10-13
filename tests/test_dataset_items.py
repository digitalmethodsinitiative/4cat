import zipfile
from unittest.mock import MagicMock

import pytest

from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException


def read_csv(path):
    """Read a CSV file the way a dataset reads its own results file"""
    dataset = MagicMock(key="abc123")
    dataset.get_results_path.return_value = path
    return DataSet._iterate_items(dataset)


def test_csv_rows_are_read(tmp_path):
    path = tmp_path / "results.csv"
    path.write_text("id,body\n1,hello\n2,world\n", encoding="utf-8")

    assert list(read_csv(path)) == [{"id": "1", "body": "hello"}, {"id": "2", "body": "world"}]


def test_row_with_more_values_than_columns_stops_reading(tmp_path):
    """
    csv.DictReader would put the extra values under the key None, which later
    crashes with an unhelpful "keywords must be strings"
    """
    path = tmp_path / "results.csv"
    path.write_text("id,body\n1,hello\n2,oops,extra,values\n3,never read\n", encoding="utf-8")

    items = read_csv(path)
    assert next(items) == {"id": "1", "body": "hello"}

    with pytest.raises(DataSetException, match=r"dataset abc123: line 3 of its CSV file has 2 more value"):
        next(items)


@pytest.fixture
def media_archive(tmp_path):
    """A video archive as 4CAT makes it: videos plus support files"""
    path = tmp_path / "results.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for filename in (".metadata.json", "video_archive", "a.mp4", "b.mp4", "b/ffmpeg_error.log"):
            archive.writestr(filename, "content")

    return path


def read_archive(path, staging_area, **kwargs):
    """Iterate a zip archive the way a dataset iterates its own results file"""
    staging_area.mkdir(exist_ok=True)
    dataset = MagicMock(key="abc123")
    dataset.get_results_path.return_value = path
    return [item["id"] for item in DataSet._iterate_archive_contents(dataset, staging_area=staging_area, **kwargs)]


def test_archive_skips_support_files(media_archive, tmp_path):
    assert read_archive(media_archive, tmp_path / "staging") == ["a.mp4", "b.mp4"]


def test_archive_includes_support_files_when_asked(media_archive, tmp_path):
    files = read_archive(media_archive, tmp_path / "staging", include_support_files=True)
    assert sorted(files) == sorted([".metadata.json", "video_archive", "a.mp4", "b.mp4", "b/ffmpeg_error.log"])
    # dotfiles come first, so a metadata file can be read before the files it describes
    assert files[0] == ".metadata.json"


def test_archive_yields_support_file_named_in_filter(media_archive, tmp_path):
    assert read_archive(media_archive, tmp_path / "staging", filename_filter=[".metadata.json"]) == [".metadata.json"]


def test_archive_offset_counts_items_only(media_archive, tmp_path):
    assert read_archive(media_archive, tmp_path / "staging", offset=1) == ["b.mp4"]
