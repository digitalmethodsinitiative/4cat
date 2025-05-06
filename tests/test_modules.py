import pytest
from unittest.mock import patch, MagicMock

from common.lib.module_loader import ModuleCollector
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

def test_module_collector(logger):
    fourcat_modules = ModuleCollector()

    # Check workers
    assert isinstance(fourcat_modules.workers, dict)
    assert len(fourcat_modules.workers) > 0
    logger.info(f"Found {len(fourcat_modules.workers)} workers")
    for worker in fourcat_modules.workers.values():
        pass

    # Check processors
    assert isinstance(fourcat_modules.processors, dict)
    assert len(fourcat_modules.processors) > 0
    logger.info(f"Found {len(fourcat_modules.processors)} processors")
    for worker in fourcat_modules.processors.values():
        pass

    # Check datasources
    assert isinstance(fourcat_modules.datasources, dict)
    assert len(fourcat_modules.datasources) > 0
    logger.info(f"Found {len(fourcat_modules.datasources)} datasources")
    for worker in fourcat_modules.datasources.values():
        pass