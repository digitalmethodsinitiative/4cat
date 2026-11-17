"""
Tests for `BasicProcessor.get_media_metadata`, which reads the media metadata
of a dataset or carries on without it
"""
from unittest.mock import MagicMock

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import MetadataException


def test_metadata_is_read_from_the_source_dataset():
    processor = MagicMock()
    metadata = BasicProcessor.get_media_metadata(processor)

    assert metadata is processor.source_dataset.read_media_metadata.return_value


def test_missing_metadata_file_is_not_logged():
    """Uploaded media has no metadata file; that is normal"""
    processor = MagicMock()
    processor.source_dataset.read_media_metadata.side_effect = FileNotFoundError("No metadata file")

    assert BasicProcessor.get_media_metadata(processor) is None
    processor.dataset.log.assert_not_called()


def test_unusable_metadata_file_is_logged_with_reason():
    processor = MagicMock()
    other_dataset = MagicMock(key="abc123")
    other_dataset.read_media_metadata.side_effect = MetadataException("Unsupported metadata schema_version 2")

    assert BasicProcessor.get_media_metadata(processor, other_dataset) is None
    message = processor.dataset.log.call_args.args[0]
    assert "abc123" in message
    assert "schema_version 2" in message
