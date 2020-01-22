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
	connection, simply takes a PID and cancels that query, then quits.
	"""
	type = "cancel-pg-query"
	max_workers = 1

	def work(self):
		"""
		Send pg_cancel_backend query to cancel query with given PID
		"""
		self.log.info("Cancelling PostgreSQL query %s" % self.job.data["remote_id"])
		self.db.execute("SELECT pg_cancel_backend(%s)" % self.job.data["remote_id"])
		self.job.finish()
