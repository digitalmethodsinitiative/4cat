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
				"overall": {
					"threads": 0,
					"posts": 0,
					"first": int(time.time()),
					"last": 0
				}
			}

			for board in config.DATASOURCES[datasource]["boards"]:
				# PostgreSQL COUNT(*) is pretty slow so we cheat and use live
				# tuples instead, which should be more or less accurate as long
				# as the autovacuum workers are doing their job
				stats[datasource] = {
					"threads": int(self.db.fetchone("SELECT n_live_tup AS num FROM pg_stat_user_tables WHERE relname = %s", ("threads_" + datasource, ))["num"]),
					"posts": int(self.db.fetchone("SELECT n_live_tup AS num FROM pg_stat_user_tables WHERE relname = %s", ("posts_" + datasource,))["num"]),
					"first": int(self.db.fetchone(
							"SELECT MIN(timestamp) AS num FROM threads_" + datasource + " WHERE is_sticky = FALSE AND timestamp > 0")["num"]),
					"last": int(self.db.fetchone(
							"SELECT MAX(timestamp_modified) AS num FROM threads_" + datasource + " WHERE is_sticky = FALSE AND timestamp > 0")["num"]),
				}

				stats["overall"]["first"] = min(stats["overall"]["first"], stats[datasource]["first"])
				stats["overall"]["last"] = max(stats["overall"]["last"], stats[datasource]["last"])
				stats["overall"]["posts"] += stats[datasource]["posts"]
				stats["overall"]["threads"] += stats[datasource]["threads"]

		outputfile = Path(config.PATH_ROOT, "stats.json")
		with outputfile.open("w") as statsfile:
			statsfile.write(json.dumps(stats))

		self.log.info("Corpus stats updated.")