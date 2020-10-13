import time
import json

from pathlib import Path

import config
from backend.abstract.worker import BasicWorker


class CorpusStats(BasicWorker):
	"""
	Calculate statistics about available data every so often
	"""
	type = "corpus-stats"
	max_workers = 1

	def work(self):
		stats = {
			"overall": {
				"threads": 0,
				"posts": 0,
				"first": int(time.time()),
				"last": 0
			}
		}

		for datasource in config.DATASOURCES:
			if "interval" not in config.DATASOURCES[datasource]:
				continue

			stats[datasource] = {
				"boards": {},
				"threads": 0,
				"posts": 0,
				"first": int(time.time()),
				"last": 0
			}

			# PostgreSQL COUNT(*) is pretty slow so we cheat and use live
			# tuples instead, which should be more or less accurate as long
			# as the autovacuum workers are doing their job
			stats[datasource]["threads"] = int(self.db.fetchone("SELECT n_live_tup AS num FROM pg_stat_user_tables WHERE relname = %s", ("threads_" + datasource,))["num"])
			stats[datasource]["posts"] = int(self.db.fetchone("SELECT n_live_tup AS num FROM pg_stat_user_tables WHERE relname = %s", ("posts_" + datasource,))["num"])
			stats[datasource]["first"] = int(self.db.fetchone("SELECT MIN(timestamp) AS num FROM threads_" + datasource + " WHERE is_sticky = FALSE AND timestamp > 0")["num"])
			stats[datasource]["last"] = int(self.db.fetchone("SELECT MAX(timestamp_modified) AS num FROM threads_" + datasource + " WHERE is_sticky = FALSE AND timestamp > 0")["num"])

			# Update stats for all datasources
			stats["overall"]["first"] = min(stats["overall"]["first"], stats[datasource]["first"])
			stats["overall"]["last"] = max(stats["overall"]["last"], stats[datasource]["last"])
			stats["overall"]["posts"] += stats[datasource]["posts"]
			stats["overall"]["threads"] += stats[datasource]["threads"]

			# Also add some details about specific boards
			for board in config.DATASOURCES[datasource]["boards"]:

				stats[datasource]["boards"][board] = {
					"first": int(self.db.fetchone(
							"SELECT MIN(timestamp) AS num FROM threads_" + datasource + " WHERE is_sticky = FALSE AND timestamp > 0 AND board = '" + board +"'")["num"]),
					"last": int(self.db.fetchone("SELECT MAX(timestamp_modified) AS num FROM threads_" + datasource + " WHERE is_sticky = FALSE AND timestamp > 0 AND board = '" + board +"'")["num"]),
					"posts": int(self.db.fetchone("SELECT count_estimate('SELECT id FROM posts_" + datasource + " WHERE board = ''" + board + "''') AS num;")["num"]), # Note: double single quotes!
					"threads": int(self.db.fetchone("SELECT count_estimate('SELECT id FROM threads_" + datasource + " WHERE board = ''" + board + "''') AS num;")["num"])
				}


		outputfile = Path(config.PATH_ROOT, "stats.json")
		with outputfile.open("w") as statsfile:
			statsfile.write(json.dumps(stats))

		self.log.info("Corpus stats updated.")