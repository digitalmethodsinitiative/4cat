import socket
import time
import json

import config
from backend.abstract.worker import BasicWorker


class InternalAPI(BasicWorker):
	"""
	Offer a local server that listens on a port for API calls and answers them
	"""
	type = "api"
	max_workers = 1

	host = config.API_HOST
	port = config.API_PORT

	def work(self):
		"""
		Listen for API requests

		Opens a socket that continuously listens for requests, and passes a
		client object on to a handling method if a connection is established

		:return:
		"""
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
					self.manager.log.info("Could not open port %i yet (%s), retrying in 10 seconds" % (self.port, e))
					time.sleep(10.0)  # wait a few seconds before retrying
					continue
				self.manager.log.error("Port %s is already in use! Local API not available." % self.port)
				return
			except ConnectionRefusedError:
				self.manager.log.error("OS refused listening at port %i! Local API not available." % self.port)
				return

		server.listen(5)
		server.settimeout(5)
		self.manager.log.info("Local API listening for requests at %s:%s" % (self.host, self.port))

		# continually listen for new connections
		while not self.interrupted:
			try:
				client, address = server.accept()
			except (socket.timeout, TimeoutError) as e:
				if self.interrupted:
					break
				# no problemo, just listen again - this only times out so it won't hang the entire app when
				# trying to exit, as there's no other way to easily interrupt accept()
				continue

			self.api_response(client, address)
			client.close()

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
					test = json.loads(buffer)
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
			remote_id = payload.get("remote_id")
			jobtype = payload.get("jobtype")
			level = payload.get("level", BasicWorker.INTERRUPT_RETRY)

			self.manager.request_interrupt(remote_id=remote_id, jobtype=jobtype, interrupt_level=level)
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
			open_jobs = self.db.fetchall("SELECT jobtype, timestamp, timestamp_claimed, timestamp_lastclaimed, interval, remote_id FROM jobs ORDER BY jobtype ASC, timestamp ASC, remote_id ASC")
			running = []
			queue = {}

			for job in open_jobs:
				try:
					worker = list(filter(lambda worker: worker.job.data["jobtype"] == job["jobtype"] and worker.job.data["remote_id"] == job["remote_id"], self.manager.worker_pool.get(job["jobtype"], [])))[0]
				except IndexError:
					worker = None

				if not bool(worker):
					if job["jobtype"] not in queue:
						queue[job["jobtype"]] = 0

					queue[job["jobtype"]] += 1
				else:
					running.append({
						"type": job["jobtype"],
						"is_claimed": job["timestamp_claimed"] > 0,
						"is_running": bool(worker),
						"is_processor": hasattr(worker, "dataset"),
						"is_recurring": (int(job["interval"]) > 0),
						"is_maybe_crashed": job["timestamp_claimed"] > 0 and not worker,
						"dataset_key": worker.dataset.key if hasattr(worker, "dataset") else None,
						"dataset_user": worker.dataset.parameters.get("user", None) if hasattr(worker, "dataset") else None,
						"dataset_parent_key": worker.dataset.top_parent().key if hasattr(worker, "dataset") else None,
						"timestamp_queued": job["timestamp"],
						"timestamp_claimed": job["timestamp_lastclaimed"]
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
