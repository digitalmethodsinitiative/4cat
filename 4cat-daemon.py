import psutil
import time
import sys
import os

import config
import backend.bootstrap as bootstrap

from backend.lib.helpers import get_absolute_folder

# check if we can run a daemon
if os.name not in ("posix", "mac"):
	print("Using 'backend.py' to run the 4CAT backend is only supported on UNIX-like systems.")
	print("Running backend in terminal instead.")
	bootstrap.run(print_logs=True)
	sys.exit(0)
