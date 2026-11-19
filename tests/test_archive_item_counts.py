"""
What `num_rows` counts for a dataset written as an archive

4CAT adds files of its own next to a dataset's own files - a `.metadata.json`,
a log from ffmpeg - and iterating the archive skips them, so they are not
items of the dataset. The two places that count files for `num_rows` leave
them out, or a dataset claims more items than anything can read back out of
it: a collector that took three screenshots and wrote one metadata file would
report four.
"""
from unittest.mock import MagicMock

from backend.lib.processor import BasicProcessor
from backend.lib.search import Search


def make_staging_area(tmp_path, filenames):
    """A staging area holding a file per name, as a producer leaves it"""
    staging_area = tmp_path / "staging"
    staging_area.mkdir()
    for filename in filenames:
        staging_area.joinpath(filename).write_text("content", encoding="utf-8")

    return staging_area


def count_for_archived(tmp_path, filenames, **kwargs):
    """
    Archive a staging area holding `filenames` and report what it counted

    :return int:  The item count the dataset was finished with
    """
    staging_area = make_staging_area(tmp_path, filenames)
    processor = MagicMock()
    processor.dataset.get_results_path.return_value = tmp_path / "results.zip"

    BasicProcessor.write_archive_and_finish(processor, staging_area, **kwargs)

    processor.dataset.finish.assert_called_once()
    return processor.dataset.finish.call_args.args[0]


def test_a_datasets_own_files_are_counted(tmp_path):
    assert count_for_archived(tmp_path, ["a.png", "b.png"]) == 2


def test_support_files_are_not_counted(tmp_path):
    """The metadata file and the log are 4CAT's, not items of the dataset"""
    assert count_for_archived(tmp_path, [".metadata.json", "a.png", "b.png", "ffmpeg.log"]) == 2


def test_a_count_the_caller_gives_is_left_alone(tmp_path):
    """A producer that knows its own count says so, e.g. because some items made no file"""
    assert count_for_archived(tmp_path, [".metadata.json", "a.png"], num_items=7) == 7


def test_data_source_archive_does_not_count_support_files(tmp_path):
    """
    A data source whose `get_items()` returns a folder, as the screenshot
    collectors do, cannot pass a count of its own: `items_to_archive` counts
    for it, so that is where its metadata file has to be left out.
    """
    staging_area = make_staging_area(tmp_path, [".metadata.json", "a.png", "b.png"])
    worker = MagicMock()
    worker.dataset.get_results_path.return_value = tmp_path / "results.zip"

    assert Search.items_to_archive(worker, staging_area, tmp_path / "results.zip") == 2
