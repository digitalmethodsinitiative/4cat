import socket
import time
import json
import os

import config
from backend.abstract.worker import BasicWorker
from backend.lib.helpers import get_absolute_folder


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

		for platform in config.PLATFORMS:
			stats[platform] = {
				"boards": {},
				"overall": {
					"threads": 0,
					"posts": 0,
					"first": int(time.time()),
					"last": 0
				}
			}

			for board in config.PLATFORMS[platform]["boards"]:
				stats[platform]["boards"][board] = {
					"threads": int(
						self.db.fetchone("SELECT COUNT(*) AS num FROM threads_" + platform + " WHERE board = %s",
										 (board,))["num"]),
					"posts": int(self.db.fetchone(
						"SELECT SUM(num_replies) AS num FROM threads_" + platform + " WHERE board = %s", (board,))[
									 "num"]),
					"first":
						int(self.db.fetchone(
							"SELECT MIN(timestamp) AS num FROM threads_" + platform + " WHERE board = %s AND timestamp > 0",
							(board,))["num"]),
					"last": int(self.db.fetchone(
						"SELECT MAX(timestamp_modified) AS num FROM threads_" + platform + " WHERE board = %s",
						(board,))["num"]),
				}

				stats[platform]["overall"]["first"] = min(stats[platform]["overall"]["first"],
														  stats[platform]["boards"][board]["first"])
				stats[platform]["overall"]["last"] = max(stats[platform]["overall"]["last"],
														 stats[platform]["boards"][board]["last"])
				stats[platform]["overall"]["posts"] += stats[platform]["boards"][board]["posts"]
				stats[platform]["overall"]["threads"] += stats[platform]["boards"][board]["threads"]

				stats["overall"]["first"] = min(stats["overall"]["first"], stats[platform]["boards"][board]["first"])
				stats["overall"]["last"] = max(stats["overall"]["last"], stats[platform]["boards"][board]["last"])
				stats["overall"]["posts"] += stats[platform]["boards"][board]["posts"]
				stats["overall"]["threads"] += stats[platform]["boards"][board]["threads"]


		outputfile = get_absolute_folder(os.path.dirname(__file__)) + "/../../stats.json"
		with open(outputfile, "w") as statsfile:
			statsfile.write(json.dumps(stats))

		self.log.info("Corpus stats updated.")