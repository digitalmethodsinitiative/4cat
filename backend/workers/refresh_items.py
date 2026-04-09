"""
Refresh items
"""
from backend.lib.worker import BasicWorker

class ItemUpdater(BasicWorker):
    """
    Refresh 4CAT items

    Refreshes settings that are dependent on external factors.
    LLM model refreshing is handled by the OllamaManager worker.
    """
    type = "refresh-items"
    max_workers = 1

    # ensure_job is intentionally disabled: this worker currently does nothing
    # and would only create unnecessary job queue churn. Re-enable when work()
    # has actual tasks to perform.
    # @classmethod
    # def ensure_job(cls, config=None):
    #     return {"remote_id": "refresh-items", "interval": 60}

    def work(self):
        # Placeholder – no tasks implemented yet.
        self.job.finish()
            