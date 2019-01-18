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
		stats = {}

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
				thread_ids = [thread["id"] for thread in self.db.fetchall("SELECT id FROM threads_" + platform + " WHERE board = %s", (board,))]
				minmax = self.db.fetchone(
					"SELECT MIN(timestamp) AS first, MAX(timestamp) AS last FROM posts_" + platform + " WHERE thread_id IN %s",
					(thread_ids,))
				stats[platform]["boards"][board] = {
					"threads": len(thread_ids),
					"posts": self.db.fetchone("SELECT COUNT(*) AS num FROM posts_" + platform + " WHERE thread_id IN %s", (thread_ids,))["num"],
					"first": minmax["first"],
					"last": minmax["last"],
				}

				stats[platform]["overall"]["first"] = min(stats[platform]["overall"]["first"], stats[platform][board]["first"])
				stats[platform]["overall"]["last"] = max(stats[platform]["overall"]["last"], stats[platform][board]["last"])
				stats[platform]["overall"]["posts"] += stats[platform]["overall"]["posts"]
				stats[platform]["overall"]["threads"] += stats[platform]["overall"]["threads"]

		outputfile = "stats.json"  #get_absolute_folder(os.path.dirname(__file__)) + "/../../stats.json"
		with open(outputfile, "w") as statsfile:
			statsfile.write(json.dumps(stats))
