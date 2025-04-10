import pytest
from unittest.mock import patch, MagicMock

from common.lib.module_loader import ModuleCollector
from backend.lib.processor import BasicProcessor
from common.lib.logger import Logger

@pytest.fixture
def mock_config(tmp_path):
    # Mock the config manager in logger to return a temporary path for logs	
    with patch("common.lib.logger.config") as mock_config:
        mock_config.get = MagicMock(side_effect=lambda key, default=None, is_json=False, user=None, tags=None: {
            "PATH_ROOT": tmp_path,
            "PATH_LOGS": tmp_path / "logs",
        }.get(key, default))
        # Create necessary directories
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
        yield mock_config

@pytest.fixture
def logger(mock_config):
    # Initialize the Logger and return it
    return Logger(logger_name="pytest", output=True, filename='test.log', log_level='DEBUG')

@pytest.fixture
def fourcat_modules():
    # Initialize the ModuleCollector and return it
    return ModuleCollector()

def test_logger(logger, mock_config):
    # Initialize the logger
    log = logger

    # Verify that mock_config.get was called
    mock_config.get.assert_any_call("PATH_LOGS")
    
    # Check if the logger is initialized correctly
    assert log is not None
    assert log.logger is not None
    assert log.logger.level == 10  # DEBUG level

    # Test logging a message
    log.info("This is a test log message.")
    
    # Check if the message was logged (you would need to check the log file in a real test)
    log_file_path = mock_config.get("PATH_LOGS") / 'test.log'
    with open(log_file_path, 'r') as f:
        logs = f.read()
        assert "This is a test log message." in logs

@pytest.mark.dependency()
def test_module_collector(logger, fourcat_modules):
    if fourcat_modules.log_buffer:
        logger.warning(fourcat_modules.log_buffer)

    # Assert workers
    assert isinstance(fourcat_modules.workers, dict)
    assert len(fourcat_modules.workers) > 0
    logger.info(f"Found {len(fourcat_modules.workers)} workers")

    # Assert processors
    assert isinstance(fourcat_modules.processors, dict)
    assert len(fourcat_modules.processors) > 0
    logger.info(f"Found {len(fourcat_modules.processors)} processors")

    # Assert datasources
    assert isinstance(fourcat_modules.datasources, dict)
    assert len(fourcat_modules.datasources) > 0
    logger.info(f"Found {len(fourcat_modules.datasources)} datasources")

    # Check if any modules could not be loaded
    if fourcat_modules.missing_modules:
        logger.error(f"Unable to import modules: {', '.join(fourcat_modules.missing_modules.keys())}")
    else:
        logger.info("No missing modules")
    assert len(fourcat_modules.missing_modules) == 0

@pytest.mark.dependency(depends=["test_module_collector"])
def test_processors(logger, fourcat_modules):
    # Iterate over all processors in fourcat_modules
    for processor_name, processor_class in fourcat_modules.processors.items():
        logger.info(f"Testing processor: {processor_name}")

        # Check if the processor is a subclass of BasicProcessor
        assert issubclass(processor_class, BasicProcessor), f"{processor_name} is not a subclass of BasicProcessor"

        # Check if required attributes are implemented
        required_attributes = ["type", "category", "title", "description", "extension"]
        for attr in required_attributes:
            assert hasattr(processor_class, attr), f"{processor_name} is missing required attribute: {attr}"
            assert getattr(processor_class, attr), f"{processor_name} has an empty value for attribute: {attr}"

        # Check if required methods are implemented
        # TODO Add "is_compatible_with" ?
        # TODO Test get_options w/ mock_dataset(s)
        required_methods = ["get_options", "process"]
        for method in required_methods:
            assert hasattr(processor_class, method), f"{processor_name} is missing required method: {method}"
            assert callable(getattr(processor_class, method)), f"{processor_name} has a non-callable method: {method}"

        logger.info(f"Processor {processor_name} passed all checks.")