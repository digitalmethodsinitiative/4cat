import threading


class KeyPoller(threading.Thread):
	"""
	Interaction poller
	Waits for key input and asks the manager loop to shutdown when someone enters "q"
	"""
	manager = None
	looping = True
	thread = False

	def __init__(self, manager=None, *args, **kwargs):
		"""
		Set up interaction poller
		:param manager: Reference to manager loop
		"""
		super().__init__(*args, **kwargs)
		self.manager = manager

	def run(self):
		"""
		Wait for input
		If input = "q", stop looping and send signal to manager thread to initiate shutdown.
		Else just wait for next input.
		"""
		while self.looping:
			cmd = input("")
			if cmd == "q":
				self.looping = False
				self.manager.abort()
