"""
Cancel a PostgreSQL query
"""
from backend.abstract.worker import BasicWorker


class QueryCanceller(BasicWorker):
	"""
	Cancel a PostgreSQL query

	psycopg2 has some limitations when it comes to asynchronous database
	manipulation. One of those is that while queries can be run sort-of
	asynchronously, it is very complicated to run *another* query while
	one is already active in the same thread, e.g. a pg_cancel_backend()
	query. To solve this complexity, this worker, with its own PG
	connection, takes the ID of a worker's Postgres connection as a
	parameter and cancels all queries associated with that connection
	"""
	type = "cancel-pg-query"
	max_workers = 1

	def work(self):
		"""
		Send pg_cancel_backend query to cancel queries for given connections
		"""
		active_queries = self.db.fetchall("SELECT pid, application_name FROM pg_stat_activity")
		pids_to_kill = [query["pid"] for query in active_queries if query["application_name"] == self.job.data["remote_id"]]

		for pid in pids_to_kill:
			self.log.info("Cancelling PostgreSQL query %s" % pid)
			self.db.execute("SELECT pg_cancel_backend(%s)" % pid)

		self.job.finish()
