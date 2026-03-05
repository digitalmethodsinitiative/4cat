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

    @classmethod
    def ensure_job(cls, config=None):
        """
        Ensure that the refresher is always running

        :return:  Job parameters for the worker
        """
        return {"remote_id": "refresh-items", "interval": 60}

    def work(self):
        self.job.finish()
            