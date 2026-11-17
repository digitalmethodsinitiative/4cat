from types import SimpleNamespace
import zipfile
from unittest.mock import MagicMock

import pytest

from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException, MapItemException
from common.lib.item_mapping import MappedItem


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


def annotated_dataset(items, num_rows, annotations=None, processor=None):
    """
    A dataset with one annotation field, whose results file holds `items`

    :param list items:  The raw items in the results file
    :param int num_rows:  The row count the dataset has stored
    :param dict annotations:  Annotation value per item id
    :param processor:  The dataset's own processor, for mapping items
    """
    annotations = annotations or {}
    dataset = MagicMock(key="abc123", num_rows=num_rows)
    dataset.annotation_fields = {"f1": {"label": "my_annotation"}}
    dataset.get_extension.return_value = "csv"
    dataset._iterate_items.return_value = iter(items)
    dataset.get_own_processor.return_value = processor
    dataset.get_annotations_for_item.side_effect = lambda item_ids, before: [
        SimpleNamespace(item_id=item_id, field_id="f1", value=annotations[item_id])
        for item_id in item_ids if item_id in annotations
    ]
    return dataset


def processor_that_cannot_map(*item_ids):
    """A processor that can map every item, except those with these ids"""
    def get_mapped_item(item):
        if item["id"] in item_ids:
            raise MapItemException(f"cannot map item {item['id']}")
        return MappedItem(item)

    processor = MagicMock()
    processor.map_item_method_available.return_value = True
    processor.get_mapped_item.side_effect = get_mapped_item
    return processor


def test_annotated_items_are_yielded_when_row_count_is_too_high():
    """For example, older archives whose row count included their metadata file"""
    dataset = annotated_dataset([{"id": "1"}, {"id": "2"}, {"id": "3"}], num_rows=4, annotations={"2": "yes"})

    items = list(DataSet.iterate_items(dataset))

    assert [item["id"] for item in items] == ["1", "2", "3"]
    assert [item["my_annotation"] for item in items] == ["", "yes", ""]


def test_annotated_items_are_yielded_when_last_item_is_unmappable():
    dataset = annotated_dataset(
        [{"id": "1"}, {"id": "2"}, {"id": "3"}], num_rows=3, annotations={"1": "yes"},
        processor=processor_that_cannot_map("3")
    )

    items = list(DataSet.iterate_items(dataset))

    assert [item["id"] for item in items] == ["1", "2"]
    assert [item["my_annotation"] for item in items] == ["yes", ""]


def test_annotated_items_are_yielded_when_stopping_at_max_unmappable():
    dataset = annotated_dataset(
        [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "4"}], num_rows=4, annotations={"1": "yes"},
        processor=processor_that_cannot_map("2", "3")
    )

    # the second unmappable item is one too many, so item 4 is never reached
    items = list(DataSet.iterate_items(dataset, max_unmappable=1))

    assert [item["id"] for item in items] == ["1"]
    assert items[0]["my_annotation"] == "yes"


def test_annotated_items_are_yielded_in_batches():
    raw_items = [{"id": str(i)} for i in range(501)]
    dataset = annotated_dataset(raw_items, num_rows=501, annotations={"0": "first", "500": ["a", "b"]})

    items = list(DataSet.iterate_items(dataset))

    # annotations are fetched once per batch of 500 items, and once for the rest
    assert [len(call.args[0]) for call in dataset.get_annotations_for_item.call_args_list] == [500, 1]
    assert [item["id"] for item in items] == [item["id"] for item in raw_items]
    assert items[0]["my_annotation"] == "first"
    assert items[1]["my_annotation"] == ""
    assert items[500]["my_annotation"] == "a,b"
