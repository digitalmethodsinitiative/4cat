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
from common.config_manager import config


class DatasourceMetrics(BasicWorker):
    """
    Calculate metrics

    This will be stored in a separate PostgreSQL table.
    """
    type = "datasource-metrics"
    max_workers = 1

    ensure_job = {"remote_id": "localhost", "interval": 43200}

    def work(self):
        self.general_stats()
        self.data_stats()

    @staticmethod
    def folder_size(path='.'):
        """
        Get the size of a folder using os.scandir for efficiency
        """
        total = 0
        for entry in os.scandir(path):
            if entry.is_file():
                total += entry.stat().st_size
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
            "size_data": DatasourceMetrics.folder_size(config.get("PATH_DATA")),
            "size_logs": DatasourceMetrics.folder_size(config.get("PATH_LOGS")),
            "size_db": self.db.fetchone("SELECT pg_database_size(%s) AS num", (config.get("DB_NAME"),))["num"]
        }

        for metric, value in metrics.items():
            self.db.upsert("metrics", {
                "metric": metric,
                "count": value,
                "datasource": "4cat",
                "board": "",
                "date": "now"
            }, constraints=["metric", "datasource", "board", "date"])

    def data_stats(self):
        """
        Go through all local datasources, and update the posts per day
        if they haven't been calculated yet. These data can then be used
        to calculate e.g. posts per month.
        :return:
        """

        # Get a list of all database tables
        all_tables = [row["tablename"] for row in self.db.fetchall(
            "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname != 'pg_catalog' AND schemaname != 'information_schema';")]

        # Check if the metrics table is already present
        metrics_exists = True if "metrics" in all_tables else False

        # If not, make it.
        if not metrics_exists:
            self.db.execute("""
				CREATE TABLE IF NOT EXISTS metrics (
				  metric             text,
				  datasource         text,
				  board              text,
				  date               text,
				  count              integer
				);

			""")

        added_datasources = [row["datasource"] for row in self.db.fetchall("SELECT DISTINCT(datasource) FROM metrics")]
        enabled_datasources = config.get("datasources.enabled", {})

        for datasource_id in self.all_modules.datasources:
            if datasource_id not in enabled_datasources:
                continue

            datasource = self.all_modules.workers.get(datasource_id + "-search")
            if not datasource:
                continue

            # Database IDs may be different from the Datasource ID (e.g. the datasource "4chan" became "fourchan" but the database ID remained "4chan")
            database_db_id = datasource.prefix if hasattr(datasource, "prefix") else datasource_id

            is_local = True if hasattr(datasource, "is_local") and datasource.is_local else False
            is_static = True if hasattr(datasource, "is_static") and datasource.is_static else False

            # Only update local datasources
            if is_local:

                # Some translating..
                settings_id = datasource_id
                if datasource_id == "4chan":
                    settings_id = "fourchan"
                elif datasource_id == "8chan":
                    settings_id = "eightchan"

                boards = [b for b in config.get(settings_id + "-search.boards", [])]

                # If a datasource is static (so not updated) and it
                # is already present in the metrics table, we don't
                # need to update its metrics anymore.
                if is_static and datasource_id in added_datasources:
                    continue
                else:

                    # -------------------------
                    #   Posts per day metric
                    # -------------------------

                    # Get the name of the posts table for this datasource
                    posts_table = datasource_id if "posts_" + database_db_id not in all_tables else "posts_" + database_db_id

                    # Count and update for every board individually
                    for board in boards:

                        if not board:
                            board_sql = " board = '' OR board = NULL"
                        else:
                            board_sql = " board='" + board + "'"

                        # Midnight of this day in UTC epoch timestamp
                        midnight = int(
                            datetime.combine(datetime.today(), time.min).replace(tzinfo=timezone.utc).timestamp())

                        # We only count passed days
                        time_sql = "timestamp < " + str(midnight)

                        # If the datasource is dynamic, we also only update days
                        # that haven't been added yet - these are heavy queries.
                        if not is_static:
                            days_added = self.db.fetchall(
                                "SELECT date FROM metrics WHERE datasource = '%s' AND board = '%s' AND metric = 'posts_per_day';" % (
                                database_db_id, board))

                            if days_added:

                                last_day_added = max([row["date"] for row in days_added])
                                last_day_added = datetime.strptime(last_day_added, '%Y-%m-%d').replace(
                                    tzinfo=timezone.utc)

                                # If the last day added is today, there's no need to update yet
                                if last_day_added.date() == datetime.today().replace(tzinfo=timezone.utc).date():
                                    self.log.info(
                                        "No new posts per day to count for %s%s" % (datasource_id, "/" + board))
                                    continue

                                # Change to UTC epoch timestamp for postgres query
                                after_timestamp = int(last_day_added.timestamp())

                                time_sql += " AND timestamp > " + str(after_timestamp) + " "

                        self.log.info(
                            "Calculating metric posts_per_day for datasource %s%s" % (datasource_id, "/" + board))

                        # Get those counts
                        query = """
							SELECT 'posts_per_day' AS metric, '%s' AS datasource, board, to_char(to_timestamp(timestamp), 'YYYY-MM-DD') AS date, count(*)COUNT
							FROM %s
							WHERE %s AND %s
							GROUP BY metric, datasource, board, date;
							""" % (database_db_id, posts_table, board_sql, time_sql)
                        # Add to metrics table
                        rows = [dict(row) for row in self.db.fetchall(query)]

                        if rows:
                            for row in rows:
                                self.db.upsert("metrics", row, constraints=["metric", "datasource", "board", "date"])

                # -------------------------------
                #   no other metrics added yet
                # -------------------------------

        self.job.finish()
