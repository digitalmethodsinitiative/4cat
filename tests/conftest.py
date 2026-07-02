"""
Shared pytest fixtures.

These mirror the fixtures in test_modules.py so that other test modules (e.g.
test_processor_map.py) can build the real module set without a database. Defining
them here makes them available session-wide; test_modules.py keeps its own local
copies, which simply override these for its own tests (standard pytest behaviour),
so nothing about that file changes.
"""
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PATH_ROOT = Path(os.path.abspath(os.path.dirname(__file__))).joinpath("..").resolve()


@pytest.fixture
def mock_database():
    """Mock the database connection."""
    with patch("common.config_manager.Database") as mock_cfg_db, \
         patch("backend.lib.worker.Database") as mock_worker_db:
        mock_database_instance = MagicMock()
        mock_cfg_db.return_value = mock_database_instance
        mock_worker_db.return_value = mock_database_instance
        yield mock_database_instance


@pytest.fixture
def mock_basic_config(tmp_path, mock_database):
    """Set up a config reader without connecting it to the database."""
    class mocked_config:
        pass

    mocked_basic_config = mocked_config()
    mocked_basic_config.get = MagicMock(side_effect=lambda key, default=None, is_json=False, user=None, tags=None: {
            "PATH_ROOT": PATH_ROOT,
            "PATH_DATA": PATH_ROOT,
            "PATH_LOGS": PATH_ROOT / "logs",
            "PATH_EXTENSIONS": PATH_ROOT / "config/extensions",
            "extensions.enabled": {},
        }.get(key, default))
    mocked_basic_config.load_user_settings = MagicMock()
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    yield mocked_basic_config


@pytest.fixture
def logger(mock_basic_config):
    """Initialize the Logger and return it."""
    from common.lib.logger import Logger
    return Logger(logger_name="pytest", output=True,
                  log_path=mock_basic_config.get("PATH_LOGS").joinpath("test.log"), log_level='DEBUG')


@pytest.fixture
def fourcat_modules(mock_basic_config):
    """The real loaded module set, built with a mocked config (no database)."""
    from common.lib.module_loader import ModuleCollector
    return ModuleCollector(config=mock_basic_config)
