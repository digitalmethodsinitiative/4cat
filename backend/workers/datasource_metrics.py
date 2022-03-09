"""
Save metrics for local datasources.
This is used for both processors (e.g. to calculate relative )
and to show how many posts a local datasource contains.
"""

from datetime import datetime, time, timezone

from backend.abstract.worker import BasicWorker
from common.lib.dataset import DataSet

import common.config_manager as config
class DatasourceMetrics(BasicWorker):
	"""
	Calculate metrics for local datasources

	This will be stored in a separate PostgreSQL table.
	"""
	type = "datasource-metrics"
	max_workers = 1

	def work(self):
		"""
		Go through all local datasources, and update the posts per day
		if they haven't been calculated yet. These data can then be used
		to calculate e.g. posts per month.
		:return:
		"""

		# Get a list of all database tables
		all_tables = [row["tablename"] for row in self.db.fetchall("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname != 'pg_catalog' AND schemaname != 'information_schema';")]

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

		for datasource_id in self.all_modules.datasources:

			datasource = self.all_modules.datasources[datasource_id]

			# Only update local datasources
			if datasource.get("is_local"):

				boards = config.get('DATASOURCES')[datasource_id].get("boards")

				if not boards:
					boards = [""]

				# If a datasource is static (so not updated) and it
				# is already present in the metrics table, we don't
				# need to update its metrics anymore.
				if datasource.get("is_static") and datasource_id in added_datasources:
						continue
				else:

					# -------------------------
					#   Posts per day metric
					# -------------------------

					# Get the name of the posts table for this datasource
					posts_table = datasource_id if "posts_" + datasource_id not in all_tables else "posts_" + datasource_id

					# Count and update for every board individually
					for board in boards:

						if not board:
							board_sql = " board = '' OR board = NULL"
						else:
							board_sql = " board='" + board + "'"

						# Midnight of this day in UTC epoch timestamp
						midnight = int(datetime.combine(datetime.today(), time.min).replace(tzinfo=timezone.utc).timestamp())

						# We only count passed days
						time_sql = "timestamp < " + str(midnight)

						# If the datasource is dynamic, we also only update days
						# that haven't been added yet - these are heavy queries.
						if not datasource.get("is_static"):

							days_added = self.db.fetchall("SELECT date FROM metrics WHERE datasource = '%s' AND board = '%s' AND metric = 'posts_per_day';" % (datasource_id, board))

							if days_added:

								last_day_added = max([row["date"] for row in days_added])
								last_day_added = datetime.strptime(last_day_added, '%Y-%m-%d').replace(tzinfo=timezone.utc)

								# If the last day added is today, there's no need to update yet
								if last_day_added.date() == datetime.today().replace(tzinfo=timezone.utc).date():
									self.log.info("No new posts per day to count for %s%s" % (datasource_id, "/" + board))
									continue

								# Change to UTC epoch timestamp for postgres query
								after_timestamp = int(last_day_added.timestamp())

								time_sql += " AND timestamp > " + str(after_timestamp) + " "

						self.log.info("Calculating metric posts_per_day for datasource %s%s" % (datasource_id, "/" + board))

						# Get those counts
						query = """
							SELECT 'posts_per_day' AS metric, '%s' AS datasource, board, to_char(to_timestamp(timestamp), 'YYYY-MM-DD') AS date, count(*)COUNT
							FROM %s
							WHERE %s AND %s
							GROUP BY metric, datasource, board, date;
							""" % (datasource_id, posts_table, board_sql, time_sql)

						# Add to metrics table
						rows = [dict(row) for row in self.db.fetchall(query)]

						if rows:
							for row in rows:
								self.db.insert("metrics", row)

					# -------------------------------
					#   no other metrics added yet
					# -------------------------------

		self.job.finish()
