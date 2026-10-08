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
