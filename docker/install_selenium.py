"""
4CAT Installation of Selenium gecko webdriver and firefox browser
"""
import subprocess
import re

if __name__ == "__main__":
	def run_command(command, error_message):
		"""
		Convenence function to run subprocess and check result
		"""
		result = subprocess.run(command.split(" "), stdout=subprocess.PIPE,
							stderr=subprocess.PIPE)

		if result.returncode != 0:
			print(error_message)
			print(command)
			print(result.stdout.decode("ascii"))
			print(result.stderr.decode("ascii"))
			exit(1)

		return result

	# Check for Linux OS
	

	print("Setting up Selenium: installing webdriver and browser")
	# Install additional packages
	PACKAGES = "wget bzip2 libgtk-3-0 libasound2 libdbus-glib-1-2 libx11-xcb1 libxtst6"
	command = f"apt-get install --no-install-recommends -y {PACKAGES}"
	run_command(command, "Error installing packages")
	print(f"Installed packages: {PACKAGES}")

	# Identify latest geckodriver
	command = "curl -i https://github.com/mozilla/geckodriver/releases/latest"
	geckodriver_github_page = run_command(command, "Error identifying latest geckodriver (curl)")

	match = re.search("v[0-9]+.[0-9]+.[0-9]+", str(geckodriver_github_page.stdout))
	if match:
		GECKODRIVER_VERSION = match.group()
	else:
		print("Error identifying latest geckodriver (regex)")
		exit(1)

	# Download and set up geckodriver
	print(f'Installing geckodriver version {GECKODRIVER_VERSION}')
	command = f"wget https://github.com/mozilla/geckodriver/releases/download/{GECKODRIVER_VERSION}/geckodriver-{GECKODRIVER_VERSION}-linux64.tar.gz"
	run_command(command, "Error downloading geckodriver")

	command = f"tar -zxf geckodriver-{GECKODRIVER_VERSION}-linux64.tar.gz -C /usr/local/bin"
	run_command(command, "Error unziping geckodriver")

	command = "chmod +x /usr/local/bin/geckodriver"
	run_command(command, "Error changing ownership of geckodriver")

	command = f"rm geckodriver-{GECKODRIVER_VERSION}-linux64.tar.gz"
	run_command(command, "Error removing temp download files")

	# Install latest firefox
	print("Installing the latest version of Firefox")
	FIREFOX_SETUP = "firefox-setup.tar.bz2"
	command = "apt-get purge firefox"
	run_command(command, "Error removing existing firefox")

	command = f'wget -O {FIREFOX_SETUP} https://download.mozilla.org/?product=firefox-latest&os=linux64'
	run_command(command, "Error downloading firefox")

	command = f"tar xjf {FIREFOX_SETUP} -C /opt/"
	run_command(command, "Error unzipping firefox")

	command = "ln -sf /opt/firefox/firefox /usr/bin/firefox"
	run_command(command, "Error creating symbolic link to firefox")

	command = f"rm {FIREFOX_SETUP}"
	run_command(command, "Error removing temp download files")

	print("Firefox and Geckodriver installation complete")
