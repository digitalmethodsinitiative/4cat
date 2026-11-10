"""
The list of processors that can be run on a dataset is worked out once per
DataSet object and config, also when that list turns out to be empty
"""
from unittest.mock import MagicMock

from common.lib.dataset import DataSet


def make_dataset(compatible_processors):
    dataset = MagicMock()
    dataset.available_processors = None
    dataset._available_processors_config = None
    dataset.get_compatible_processors.return_value = compatible_processors
    dataset.get_children.return_value = []
    return dataset


def test_empty_list_is_worked_out_once():
    dataset = make_dataset({})

    assert DataSet.get_available_processors(dataset) == {}
    assert DataSet.get_available_processors(dataset, exclude_hidden=True) == {}
    dataset.get_compatible_processors.assert_called_once()


def test_list_is_worked_out_once_and_hidden_processors_filtered_per_call():
    visible = MagicMock(is_hidden=False)
    hidden = MagicMock(is_hidden=True)
    dataset = make_dataset({"visible": visible, "hidden": hidden})

    assert DataSet.get_available_processors(dataset) == {"visible": visible, "hidden": hidden}
    assert DataSet.get_available_processors(dataset, exclude_hidden=True) == {"visible": visible}
    dataset.get_compatible_processors.assert_called_once()


def test_list_is_reused_for_the_same_config():
    config = MagicMock()
    dataset = make_dataset({"some-processor": MagicMock(is_hidden=False)})

    DataSet.get_available_processors(dataset, config=config)
    DataSet.get_available_processors(dataset, config=config)
    dataset.get_compatible_processors.assert_called_once_with(config=config)


def test_list_is_worked_out_again_for_another_config():
    """
    A processor may be available to one user and not to another, e.g.
    because of their privileges
    """
    processor = MagicMock(is_hidden=False)
    first_user_config = MagicMock()
    second_user_config = MagicMock()
    dataset = make_dataset({})
    dataset.get_compatible_processors.side_effect = lambda config: (
        {"some-processor": processor} if config is first_user_config else {}
    )

    assert DataSet.get_available_processors(dataset, config=first_user_config) == {"some-processor": processor}
    assert DataSet.get_available_processors(dataset, config=second_user_config) == {}
    assert DataSet.get_available_processors(dataset, config=first_user_config) == {"some-processor": processor}
    assert dataset.get_compatible_processors.call_count == 3
