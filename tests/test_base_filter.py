"""
Tests for `BaseFilter`, the shared part of 4CAT's filter processors
"""
import zipfile
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.lib.processor import BasicProcessor
from common.lib.dataset import DataSet
from processors.filtering.base_filter import BaseFilter
from processors.filtering.column_filter import ColumnFilter


"""
How a filter's dataset ends.

A filter can end with a warning, for example when the column filter keeps the
top 2 values but more items have them than fit. The warning has to survive
the moment the base filter finishes the dataset: before this was fixed, the
message stayed but the dataset was marked as a plain success.

These tests run the real column filter and the real dataset status handling;
only the database and the files are left out.
"""


class Item(dict):
    """An item as datasets give them to processors: the mapped values, with the original data"""
    @property
    def original(self):
        return dict(self)


class FakeSource:
    def __init__(self, values):
        self.items = [Item(id=str(number), category=value) for number, value in enumerate(values)]
        self.num_rows = len(self.items)

    def iterate_items(self, processor=None, **kwargs):
        yield from self.items

    def get_extension(self):
        return "csv"

    def num_annotations(self):
        return 0

    def get_label(self):
        return "source"


def make_dataset(tmp_path):
    """A real dataset object, without a database or files behind it"""
    dataset = DataSet.__new__(DataSet)
    dataset.key = "abc123"
    dataset.data = {"key": "abc123", "status": "", "status_type": "processing", "is_finished": False}
    dataset.db = MagicMock()
    dataset.db.update.return_value = 1
    dataset.no_status_updates = False
    dataset.preset_parent = []
    dataset.log = MagicMock()
    dataset.update_label = MagicMock()
    dataset.get_results_path = lambda: tmp_path / "filtered.csv"
    return dataset


def run_filter(values, parameters, tmp_path):
    processor = ColumnFilter.__new__(ColumnFilter)
    processor.source_dataset = FakeSource(values)
    processor.dataset = make_dataset(tmp_path)
    processor.parameters = parameters
    processor.interrupted = False
    processor.process()
    return processor.dataset


TOP_2_STRICT = {"column": "category", "match-style": "top-top", "top-n": 2, "strict-top": True, "match-value": ""}


def test_warning_is_kept_when_finishing(tmp_path):
    # the top 2 values are "c" and "b", but with "strict" only 2 items may be kept, so one "b" is left out
    dataset = run_filter(["a", "a", "a", "b", "b", "c"], TOP_2_STRICT, tmp_path)

    assert dataset.data["is_finished"]
    assert dataset.data["num_rows"] == 2
    assert dataset.data["status_type"] == "warning"
    assert "1 were excluded" in dataset.data["status"]


def test_without_warning_the_dataset_finishes_normally(tmp_path):
    dataset = run_filter(["a", "b", "c"], TOP_2_STRICT, tmp_path)

    assert dataset.data["num_rows"] == 2
    assert dataset.data["status_type"] == "finished"


"""
Filtering an archive dataset.

A filter copies the kept files into a new archive, and the archive's
.metadata.json along with them so the files can still be traced back to the
items they were downloaded for. Not every archive has one: an upload of loose
media files does not, and filtering such an archive used to fail.
"""


def run_archive_filter(tmp_path, archive_contents):
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
    processor.dataset.data = {}
    processor.filter_items.return_value = [SimpleNamespace(original={"id": "a.jpg"}, file=image)]
    processor.extract_archived_file_by_name = lambda *args: BasicProcessor.extract_archived_file_by_name(processor, *args)

    BaseFilter.process(processor)
    return staging_area, processor.write_archive_and_finish


def test_filter_archive_without_metadata(tmp_path):
    """An archive without .metadata.json (e.g. uploaded media) can be filtered"""
    staging_area, write_archive_and_finish = run_archive_filter(tmp_path, ["a.jpg"])

    assert sorted(file.name for file in staging_area.iterdir()) == ["a.jpg"]
    write_archive_and_finish.assert_called_once_with(staging_area, 1, warning=None)


def test_filter_archive_keeps_metadata(tmp_path):
    staging_area, write_archive_and_finish = run_archive_filter(tmp_path, [".metadata.json", "a.jpg"])

    assert sorted(file.name for file in staging_area.iterdir()) == [".metadata.json", "a.jpg"]
    write_archive_and_finish.assert_called_once_with(staging_area, 1, warning=None)
