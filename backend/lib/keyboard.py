"""
Simple class responsible for capturing user input
"""
import threading


class KeyPoller(threading.Thread):
	"""
	Interaction poller

	Waits for key input and asks the main loop to shutdown when someone enters "q"
	"""
	main = None
	looping = True
	thread = False

	def __init__(self, main=None):
		"""
		Set up interaction poller
		:param main: Reference to main loop
		"""
		super().__init__()
		self.main = main

	def run(self):
		"""
		Wait for input

		If input = "q", stop looping and send signal to main thread to initiate shutdown.
		Else just wait for next input.
		"""
		while self.looping:
			cmd = input("")
			if cmd == "q":
				self.looping = False
				self.main.abort()
