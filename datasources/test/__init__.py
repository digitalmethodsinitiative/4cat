"""
Test datasource (development only)

Provides a dummy "search" worker that creates datasets in deliberately distinct
states (completing normally, running forever, or crashing) so the worker-status
and queue admin pages can be exercised without running a real data collection.

The search worker only registers itself when the
``FOURCAT_ENABLE_TEST_DATASOURCE`` environment variable is set to a truthy
value, so this datasource is inert (no worker, nothing runnable) on a normal or
production instance even though the folder is present.

See ``helper-scripts/create_test_jobs.py`` for enqueuing one of each state.
"""
import os

# only register this datasource when explicitly enabled, so it is inert on a
# normal/production instance. This MUST match the gate on the search worker in
# search_test.py: if the datasource registers without its worker,
# manager.validate_datasources() errors with "No search worker defined".
if os.environ.get("FOURCAT_ENABLE_TEST_DATASOURCE", "").lower() in ("1", "true", "yes", "on"):
    # Use default data source init function
    from common.lib.helpers import init_datasource as init_datasource

    # Internal identifier for this data source
    DATASOURCE = "test"
    NAME = "Test datasource (dev only)"
else:
    # deliberately inert on a normal/production instance; tell the loader
    # this is intentional so it doesn't warn about missing attributes
    DATASOURCE_DISABLED = True
