import traceback
from traceback import FrameSummary

import pytest
import time
import json
from pathlib import Path
import os
from unittest.mock import patch, MagicMock

"""
In order to ensure imports do not instantiate objects (e.g., `from config_manager import config`),
we import within the test functions and utilize pytest.fixtures to mock the necessary components
(e.g., `config`).
"""

PATH_ROOT = Path(os.path.abspath(os.path.dirname(__file__))).joinpath("..").resolve()

@pytest.fixture
def mock_database():
    """
    Mock the database connection.
    """
    with patch("common.config_manager.Database") as mock_cfg_db, \
         patch("backend.lib.worker.Database") as mock_worker_db:
        mock_database_instance = MagicMock()
        mock_cfg_db.return_value = mock_database_instance
        mock_worker_db.return_value = mock_database_instance
        yield mock_database_instance

@pytest.fixture
def mock_basic_config(tmp_path, mock_database):
    """
    Set up a config reader without connecting it to the database
    """
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
    # Create necessary directories
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    yield mocked_basic_config
       
@pytest.fixture
def logger(mock_basic_config):
    """
    Initialize the Logger and return it.

    This also allows us to use our Logger for testing.
    """
    from common.lib.logger import Logger
    return Logger(logger_name="pytest", output=True, log_path=mock_basic_config.get("PATH_LOGS").joinpath("test.log"), log_level='DEBUG')

def test_logger(logger, mock_basic_config):
    # Initialize the logger
    log = logger

    # Verify that mock_config.get was called
    mock_basic_config.get.assert_any_call("PATH_LOGS")
    
    # Check if the logger is initialized correctly
    assert log is not None
    assert log.logger is not None
    assert log.logger.level == 10  # DEBUG level

    # Test logging a message
    log.info("This is a test log message.")
    
    # Check if the message was logged (you would need to check the log file in a real test)
    log_file_path = mock_basic_config.get("PATH_LOGS") / 'test.log'
    with open(log_file_path, 'r') as f:
        logs = f.read()
        assert "This is a test log message." in logs

@pytest.fixture
def fourcat_modules(mock_basic_config):
    from common.lib.module_loader import ModuleCollector
    # Initialize the ModuleCollector and return it
    return ModuleCollector(config=mock_basic_config)

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


@pytest.fixture
def mock_job():
    with patch("common.lib.job.Job") as mock_job:
        mock_job_instance = MagicMock()
        mock_job_instance.data = {
            "id": "test_job_id",  # Provide a realistic job ID
        }
        mock_job.return_value = mock_job_instance
        yield mock_job_instance

@pytest.fixture
def mock_job_queue():
    # Mock the job queue
    with patch("common.lib.queue.JobQueue") as mock_job_queue:
        mock_job_queue_instance = MagicMock()
        mock_job_queue.return_value = mock_job_queue_instance
        yield mock_job_queue_instance

def test_worker_initialization(mock_database, mock_job, mock_job_queue):
    # Mostly to ensure testing and mocks are working as appropriate, but also check BasicWorker inits
    from backend.lib.worker import BasicWorker

    class TestWorker(BasicWorker):
        def work(self):
            pass

    # Initialize the worker with mocks
    TestWorker(
        logger=MagicMock(),
        job=mock_job,
        queue=mock_job_queue,
        manager=MagicMock(),
        modules=MagicMock()
    )

@pytest.fixture
def mock_dataset_database():
    # Mock the database connection in dataset
    with patch("common.lib.database.Database") as mock_database:
        mock_database_instance = MagicMock()
        # This should be a dataset record
        mock_database_instance.fetchone.return_value = {
            "key": "test_dataset",
            "query": "pytest_test_dataset",
            "parameters": json.dumps({"test": "parameters"}),
            "result_file": "",
            "creator": "test_owner",
            "status": "",
            "type": "test_type",
            "timestamp": int(time.time()),
            "is_finished": False,
            "is_private": False,
            "software_version": "4cat_test",
            "software_source": "pytest",
            "software_file": "",
            "num_rows": 0,
            "progress": 0.0,
            "key_parent": ""
        }
        mock_database.return_value = mock_database_instance
        yield mock_database_instance

@pytest.fixture
def mock_dataset(mock_dataset_database, fourcat_modules):
    from common.lib.dataset import DataSet
    # Patch the refresh_owners method to prevent it from running
    # Patch get_parent to return a mock object; some get_options methods expect it (usually would not run due to is_compatible_with)
    with patch.object(DataSet, "refresh_owners", return_value=None), \
         patch.object(DataSet, "get_parent", return_value=MagicMock(type="test_parent")):
        dataset = DataSet(key="test_dataset", db=mock_dataset_database, modules=fourcat_modules)
        yield dataset


@pytest.mark.dependency(depends=["test_module_collector"])
def test_processors(logger, fourcat_modules, mock_job, mock_job_queue, mock_dataset, mock_database, mock_basic_config):
    """
    Test all processors separately ensuring they are valid and can be instantiated and report all failures at the end.
    """
    from backend.lib.processor import BasicProcessor

    failures = []  # Collect failures for reporting

    # Iterate over all processors in fourcat_modules
    for processor_name, processor_class in fourcat_modules.processors.items():
        logger.info(f"Testing processor: {processor_name}")

        try:
            # Check if the processor is a subclass of BasicProcessor
            assert issubclass(processor_class, BasicProcessor), f"{processor_name} is not a subclass of BasicProcessor"

            # Check if required attributes are implemented
            required_attributes = ["type", "category", "title", "description", "extension"]
            for attr in required_attributes:
                assert hasattr(processor_class, attr), f"{processor_name} is missing required attribute: {attr}"
                assert getattr(processor_class, attr), f"{processor_name} has an empty value for attribute: {attr}"

            # Check if required methods are implemented
            required_methods = ["get_options", "process"]
            for method in required_methods:
                assert hasattr(processor_class, method), f"{processor_name} is missing required method: {method}"
                assert callable(getattr(processor_class, method)), f"{processor_name} has a non-callable method: {method}"

            # Test get_options with mock_dataset
            try:
                processor_class.get_options(parent_dataset=mock_dataset, config=mock_basic_config)
            except Exception as e:
                # Log the failure and add it to the failures list
                trace = get_trace(traceback.TracebackException.from_exception(e).stack)
                logger.error(f"Processor {processor_name} failed in get_options: {e} (in {trace.filename.split('/')[-1]}:{trace.lineno})")
                failures.append((processor_name, str(e)))

            # Check if processor Class has "options" attribute
            if hasattr(processor_class, "options"):
                logger.error(f"{processor_name} has deprecated 'options' attribute; use get_options() method instead.")
                failures.append((processor_name, "'options' attribute is deprecated"))

            # Check if the processor can be instantiated
            try:
                processor_class(logger, job=mock_job, queue=mock_job_queue, manager=None, modules=fourcat_modules)
            except Exception as e:
                trace = get_trace(traceback.TracebackException.from_exception(e).stack)
                logger.error(f"Processor {processor_name} failed in process(): {e} (in {trace.filename.split('/')[-1]}:{trace.lineno})")
                failures.append((processor_name, str(e)))

        except Exception as e:
            trace = get_trace(traceback.TracebackException.from_exception(e).stack)
            logger.error(f"Processor {processor_name} failed while setting up: {e} (in {trace.filename.split('/')[-1]}:{trace.lineno})")
            failures.append((processor_name, str(e)))


    # Report all failures at the end
    if failures:
        names = [name for name, _ in failures]
        failure_messages = "\n".join([f"{name}: {error}" for name, error in failures])
        pytest.fail(f"The following processors failed: {names}\n{failure_messages}")
    else:
        logger.info("All processors passed successfully.")

@pytest.mark.dependency(depends=["test_module_collector"])
def test_compatibility_coverage(logger, fourcat_modules):
    """
    Every concrete, non-collector processor should express its input contract.
    Three states, differentiated:

    * declares a `compatibility` (a Compatibility instance) -- fully covered;
    * keeps an `is_compatible_with` override but NO coarse Compatibility --
      "covered" for runtime, but *opaque to the processor map*: it can't place the
      processor without at least a coarse spec. Surfaced as a warning, not a
      failure;
    * neither -- a hard failure: it silently rides the BasicProcessor default,
      which is almost never intended.

    Collectors (datasources) consume uploads/queries, not an existing dataset, so
    they have no consumer-side compatibility and are exempt. Abstract bases that
    genuinely run on nothing use the `Compatibility(types=set())` convention,
    which counts as declared.
    """
    from backend.lib.processor import BasicProcessor
    from backend.lib.search import Search
    from common.lib.compatibility import Compatibility

    base_method = BasicProcessor.is_compatible_with.__func__
    stragglers = []       # neither a Compatibility nor an override -- hard failure
    override_only = []    # an override but no coarse Compatibility -- opaque to the map

    for name, processor_class in fourcat_modules.processors.items():
        # collectors run on no dataset (a Search subclass, or a -search/-import type)
        if issubclass(processor_class, Search) or name.endswith(("-search", "-import")):
            continue

        if isinstance(getattr(processor_class, "compatibility", None), Compatibility):
            continue  # fully covered

        own_method = getattr(processor_class.is_compatible_with, "__func__", None)
        if own_method is not None and own_method is not base_method:
            override_only.append(name)
        else:
            stragglers.append(name)

    # surfaced, not failed: an override with no coarse Compatibility is opaque to
    # the map -- it has no spec to read, so it can't place the processor at all
    if override_only:
        logger.warning(
            f"{len(override_only)} processor(s) keep an is_compatible_with override but declare no "
            f"coarse Compatibility (opaque to the map; a coarse spec would help): {sorted(override_only)}"
        )

    if stragglers:
        logger.error(f"{len(stragglers)} processor(s) have neither a Compatibility nor an override: {sorted(stragglers)}")
        pytest.fail(
            "These processors declare no Compatibility and keep no is_compatible_with override "
            f"(they silently ride the BasicProcessor default): {sorted(stragglers)}"
        )

    logger.info(
        f"Compatibility coverage OK ({len(fourcat_modules.processors)} processors; "
        f"{len(override_only)} override-only, 0 stragglers)."
    )


@pytest.mark.dependency(depends=["test_module_collector"])
def test_datasources(logger, fourcat_modules, mock_job, mock_job_queue, mock_dataset, mock_database):
    from backend.lib.search import Search

    failures = []  # Collect failures for reporting

    # Iterate over all processors in fourcat_modules
    for processor_name, processor_class in fourcat_modules.processors.items():
        try:
            # Identify Search processors and ensure they were named correctly
            if issubclass(processor_class, Search):
                assert (processor_name.replace("-search", "") in fourcat_modules.datasources or processor_name.replace("-import", "") in fourcat_modules.datasources), f"Search worker type {processor_name} is does not appear to be paired with a datasource; please check the naming convention (e.g., {processor_name}-search or {processor_name}-import)."

        except Exception as e:
            # Log the failure and add it to the failures list
            logger.error(f"Datasource {processor_name} failed: {e}")
            failures.append((processor_name, str(e)))

    for datasource_name, datasource_data in fourcat_modules.datasources.items():
        if datasource_name in ["twitter"]:
            # Skip datasources that are not meant to be tested
            # datasource_name is the same as type minus the "-search" (or in error cases "-import") suffix
            # this includes bug https://github.com/digitalmethodsinitiative/4cat/issues/493 which likely needs migrate script fix
            continue
        try:
            assert datasource_data.get("has_worker", False), f"Datasource {datasource_name} does not have a worker"
          
        except Exception as e:
            # Log the failure and add it to the failures list
            logger.error(f"Datasource {datasource_name} failed: {e}")
            failures.append((datasource_name, str(e)))
    
    # Report all failures at the end
    if failures:
        names = [name for name, _ in failures]
        failure_messages = "\n".join([f"{name}: {error}" for name, error in failures])
        pytest.fail(f"The following datasources failed: {names}\n{failure_messages}")
    else:
        logger.info("All datasources passed successfully.")


def test_dataset_finish_raises_on_double_finish(mock_dataset):
    """
    Regression guard for common/lib/dataset.py:986.

    A second finish() call on an already-finished dataset would silently
    overwrite status_type (e.g. downgrade WARNING → SUCCESS), since finish()
    writes status_type directly via db.update and is not protected by the
    no_status_updates flag that guards update_status. The raise turns that
    silent corruption into a loud failure. If this test starts failing
    because finish() was made idempotent, that change re-introduces the
    bug class fixed in processors/metrics/url_titles.py.
    """
    from common.lib.dataset import StatusType

    mock_dataset.data["is_finished"] = True
    mock_dataset.data["status_type"] = StatusType.WARNING.value

    with pytest.raises(RuntimeError, match="finished"):
        mock_dataset.finish(5)

def get_trace(stack) -> FrameSummary:
    """
    Get relevant stack trace frame

    Skips over frames that are from (frozen) internal libraries

    :param stack:
    :return FrameSummary:
    """
    bit = stack.pop()
    while stack and not bit.filename.startswith(str(PATH_ROOT)):
        bit = stack.pop()

    return bit