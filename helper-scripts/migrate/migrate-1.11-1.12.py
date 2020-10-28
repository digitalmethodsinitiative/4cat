# check for presence of chromium and chromedriver and if they are compatible
import subprocess

print("  Looking for chromedriver...")
version = None
try:
	version = subprocess.run(["chromedriver", "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
except Exception as e:
	print("  Exception: %s" % e)

if not version or version.returncode != 0:
	print("  Chromedriver is not available. Make sure that:")
	print("  - Chromedriver is installed")
	print("  - The binary can be called as 'chromedriver'")
	print("  - The folder where the binary is located has been added to PATH")
	print("  You can download chromedriver at:\n    https://sites.google.com/a/chromium.org/chromedriver/downloads")
	print("  Chromedriver is required for the TikTok data source. If you do not install it now,")
	print("  later versions of 4CAT may not work, and you cannot enable the TikTok data source.")
	print("  Do you want to continue without installing chromedriver? [y/n]", end="")
	if input("").lower() == "y":
		print()
		exit(0)
	else:
		print("\n  Install chromedriver and run this script again.")
		exit(1)
else:
	chromedriver_version_str = version.stdout.decode("utf-8").split(" ")[1]
	chromedriver_version_maj = int(chromedriver_version_str.split(".")[0])
	print("  Chromedriver version %i (%s) found!" % (chromedriver_version_maj, chromedriver_version_str))


from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException, SessionNotCreatedException
options = Options()
options.headless = True
options.add_argument('--headless')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')

try:
	browser = webdriver.Chrome(options=options)
	browser.get("https://w3.org")
	browser.close()
except (SessionNotCreatedException, WebDriverException) as e:
	if "binary not found" in str(e):
		print("  Chromium binary is not available.", end="")
	if "only supports Chrome" in str(e):
		print("  Your chromedriver version is incompatible with your Chromium version:\n  (%s)" % e)
	else:
		print("  Could not connect to Chromium (%s)." % e, end="")

	print("  Make sure that:")
	print("  - Chromium is installed")
	print("  - It is compatible with chromedriver version %s" % chromedriver_version_str)
	print("  - The binary can be found by chromedriver")
	print("  - The folder where the binary is located has been added to PATH")
	print("  Usually, installing Chrome is enough to accomplish this.")
	print("  On Windows and MacOS, you may also need to start Chrome at least once.")
	exit(1)

print("  Succesfully launched chromium via chromedriver and Selenium!")