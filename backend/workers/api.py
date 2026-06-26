import socket
import time
import json

from backend.lib.worker import BasicWorker
from common.lib.job import Job
from common.lib.exceptions import JobNotFoundException


class InternalAPI(BasicWorker):
	"""
	Offer a local server that listens on a port for API calls and answers them
	"""
	type = "api"
	max_workers = 1

	host = None
	port = None

	@classmethod
	def ensure_job(cls, config=None):
		"""
		Ensure that the API worker is always running

		This is used to ensure that the API worker is always running, and if it
		is not, it will be started by the WorkerManager.

		:return:  Job parameters for the worker
		"""
		return {"remote_id": "localhost"}

	def work(self):
		"""
		Listen for API requests

		Opens a socket that continuously listens for requests, and passes a
		client object on to a handling method if a connection is established

		:return:
		"""
		self.host = self.config.get('API_HOST')
		self.port = self.config.get('API_PORT')

		if self.port == 0:
			# if configured not to listen, just loop until the backend shuts
			# down we can't return here immediately, since this is a worker,
			# and workers that end just get started again
			self.db.close()
			self.manager.log.info("Local API not available per configuration")
			while not self.interrupted:
				time.sleep(1)
			return

		# set up the socket
		server = socket.socket()
		server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		server.settimeout(2)  # should be plenty

		has_time = True
		start_trying = int(time.time())
		while has_time:
			has_time = start_trying > time.time() - 300  # stop trying after 5 minutes
			try:
				server.bind((self.host, self.port))
				break
			except OSError as e:
				if has_time and not self.interrupted:
					self.manager.log.info(f"Could not open port {self.port} yet ({e}), retrying in 10 seconds")
					time.sleep(10.0)  # wait a few seconds before retrying
					continue
				self.manager.log.error(f"Cannot listen at port {self.port} ({e})! Local API not available. Check if a residual 4CAT process may still be listening at the port.")
				return
			except ConnectionRefusedError as e:
				self.manager.log.error(f"OS refused listening at port {self.port} ({e})! Local API not available.")
				return

		server.listen()
		server.settimeout(2)
		self.manager.log.info("Local API listening for requests at %s:%s" % (self.host, self.port))

		# continually listen for new connections
		client = None
		while not self.interrupted:
			try:
				client, address = server.accept()
			except (socket.timeout, TimeoutError):
				if self.interrupted:
					break
				# no problemo, just listen again - this only times out so it won't hang the entire app when
				# trying to exit, as there's no other way to easily interrupt accept()
				continue

			self.api_response(client, address)

		if client:
			client.close()

		server.close()
		self.manager.log.info("Shutting down local API server")

	def api_response(self, client, address):
		"""
		Respond to API requests

		Gets the request, parses it as JSON, and if it is indeed JSON and of
		the proper format, a response is generated and returned as JSON via
		the client object

		:param client:  Client object representing the connection
		:param tuple address:  (IP, port) of the request
		:return: Response
		"""
		client.settimeout(2)  # should be plenty

		try:
			buffer = ""
			while True:
				# receive data in 1k chunks
				try:
					data = client.recv(1024).decode("ascii")
				except UnicodeDecodeError:
					raise InternalAPIException

				buffer += data
				if not data or data.strip() == "" or len(data) > 2048:
					break

				# start processing as soon as we have valid json
				try:
					json.loads(buffer)
					break
				except json.JSONDecodeError:
					pass

			if not buffer:
				raise InternalAPIException
		except (socket.timeout, TimeoutError, ConnectionError, InternalAPIException):
			# this means that no valid request was sent
			self.manager.log.info("No input on API call from %s:%s - closing" % address)
			return False

		self.manager.log.debug("Received API request from %s:%s" % address)

		try:
			payload = json.loads(buffer)
			if "request" not in payload:
				raise InternalAPIException

			response = self.process_request(payload["request"], payload)
			if not response:
				raise InternalAPIException

			response = json.dumps({"error": False, "response": response})
		except (json.JSONDecodeError, InternalAPIException):
			response = json.dumps({"error": "Invalid JSON"})

		try:
			response = client.sendall(response.encode("ascii"))
		except (BrokenPipeError, ConnectionError, socket.timeout):
			response = None

		return response

	def process_request(self, request, payload):
		"""
		Generate API response

		Checks the type of request, and returns an appropriate response for
		the type.

		:param str request:  Request identifier
		:param payload:  Other data sent with the request
		:return:  API response
		"""
		if request == "cancel-job":
			# cancel a running job
			payload = payload.get("payload", {})
			level = payload.get("level", BasicWorker.INTERRUPT_RETRY)
			try:
				job = Job.get_by_remote_ID(jobtype=payload.get("jobtype"), remote_id=payload.get("remote_id"), database=self.db)
			except JobNotFoundException:
				return {"error": "Job not found"}

			self.manager.request_interrupt(job=job, interrupt_level=level)
			return "OK"

		elif request == "workers":
			# return the number of workers, sorted by type
			workers = {}
			for jobtype in self.manager.worker_pool:
				workers[jobtype] = len(self.manager.worker_pool[jobtype])

			workers["total"] = sum([workers[workertype] for workertype in workers])

			return workers

		if request == "jobs":
			# return queued jobs, sorted by type
			jobs = self.db.fetchall("SELECT * FROM jobs")
			if jobs is None:
				return {"error": "Database unavailable"}

			response = {}
			for job in jobs:
				if job["jobtype"] not in response:
					response[job["jobtype"]] = 0
				response[job["jobtype"]] += 1

			response["total"] = sum([response[jobtype] for jobtype in response])

			return response

		if request == "datasets":
			# datasets created per time period
			week = 86400 * 7
			now = int(time.time())

			items = self.db.fetchall("SELECT * FROM datasets WHERE timestamp > %s ORDER BY timestamp ASC", (now - week,))

			response = {
				"1h": 0,
				"1d": 0,
				"1w": 0
			}

			for item in items:
				response["1w"] += 1
				if item["timestamp"] > now - 3600:
					response["1h"] += 1
				if item["timestamp"] > now - 86400:
					response["1d"] += 1

			return response

		if request == "worker-status":
			# technically more 'job status' than 'worker status', this returns
			# all jobs plus, for those that are currently active, some worker
			# info as well as related datasets. useful to monitor server
			# activity and judge whether 4CAT can safely be interrupted
			open_jobs = self.db.fetchall(
				"SELECT jobtype, queue_id, timestamp, timestamp_claimed, timestamp_lastclaimed, interval, remote_id "
				"FROM jobs ORDER BY queue_id ASC, jobtype ASC, timestamp ASC, remote_id ASC"
			)
			running = []
			queue = {}

			for job in open_jobs:
				# find the worker for this job, if it exists
				queue_key = job["queue_id"]
				jobtype = job["jobtype"]

				worker = None
				for candidate in self.manager.worker_pool.get(queue_key, []):
					candidate_data = candidate.job.data
					if (
						candidate_data.get("remote_id") == job["remote_id"]
						# can be various jobtypes in same queue (and theoretically remote_id could be same across jobtypes)
						and candidate_data.get("jobtype") == jobtype
					):
						worker = candidate
						break
				
				# a job's claim flag encodes three states:
				#   0  -> queued/claimable
				#  >0  -> claimed (running if a live worker exists, else a likely
				#        hard-kill zombie)
				#  -1  -> parked after a crash (Job.STATUS_PARKED); retried on the
				#        next restart. see Job.park() / BasicWorker.run().
				timestamp_claimed = job["timestamp_claimed"]
				is_claimed = timestamp_claimed > 0
				is_parked = timestamp_claimed == Job.STATUS_PARKED

				if not worker and not is_claimed and not is_parked:
					# truly queued and waiting to be claimed
					if jobtype not in queue:
						queue[jobtype] = 0
					queue[jobtype] += 1
				else:
					# has a live worker, or is claimed/parked without one. dataset
					# resolution is left to the frontend (which treats remote_id as
					# a dataset key only for processor jobtypes); the API just
					# reports job state.
					running.append({
						"type": jobtype,
						"queue_id": queue_key,
						"remote_id": job["remote_id"],
						"is_claimed": is_claimed,
						"is_running": bool(worker),
						# Processors have DataSets
						"is_processor": jobtype in self.modules.processors,
						"is_recurring": (int(job["interval"]) > 0),
						"is_parked": is_parked,
						"is_maybe_crashed": is_claimed and not bool(worker),
						"timestamp_queued": job["timestamp"],
						"timestamp_claimed": timestamp_claimed,
						"timestamp_lastclaimed": job["timestamp_lastclaimed"],
					})

			return {
				"running": running,
				"queued": queue
			}



		# no appropriate response
		return False


class InternalAPIException(Exception):
	# raised if API request could not be parsed
	pass
