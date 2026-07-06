"""
Calculate various 4CAT metrics

Two types of metrics are currently calculated:

- General metrics. Currently this is mostly the total dataset size, which is
  useful to know for admins
- Datasource metrics. This is used for both processors (e.g. to calculate
  relative) and to show how many posts a local datasource contains.
"""
import os

from datetime import datetime, time, timezone

from backend.lib.worker import BasicWorker


class DatasourceMetrics(BasicWorker):
    """
    Calculate metrics

    This will be stored in a separate PostgreSQL table.
    """
    type = "datasource-metrics"
    max_workers = 1

    @classmethod
    def ensure_job(cls, config=None):
        """
        Ensure that the datasource metrics worker is always running

        This is used to ensure that the datasource metrics worker is always
        running, and if it is not, it will be started by the WorkerManager.

        :return:  Job parameters for the worker
        """
        return {"remote_id": "localhost", "interval": 40000}

    def work(self):
        self.general_stats()

    @staticmethod
    def folder_size(path='.'):
        """
        Get the size of a folder using os.scandir for efficiency
        """
        total = 0
        for entry in os.scandir(path):
            if entry.is_file():
                try:
                    total += entry.stat().st_size
                except FileNotFoundError:
                    # If the file was removed while scanning, skip it
                    continue
            elif entry.is_dir():
                total += DatasourceMetrics.folder_size(entry.path)
        return total

    def general_stats(self):
        """
        Calculate general 4CAT stats

        These sizes can be very slow to calculate, which is why we do it in
        this worker instead of on demand.
        """
        metrics = {
            "size_data": DatasourceMetrics.folder_size(self.config.get("PATH_DATA")),
            "size_logs": DatasourceMetrics.folder_size(self.config.get("PATH_LOGS")),
            "size_db": self.db.fetchone("SELECT pg_database_size(%s) AS num", (self.config.get("DB_NAME"),))["num"]
        }

        for metric, value in metrics.items():
            self.db.upsert("metrics", {
                "metric": metric,
                "count": value,
                "datasource": "4cat",
                "board": "",
                "date": "now"
            }, constraints=["metric", "datasource", "board", "date"])