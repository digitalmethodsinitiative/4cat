"""
4CAT Migration agent

4CAT updates may involve backwards-incompatible changes that would make it
unable to run after restarting when a new version is pulled. To avoid this,
all backwards-incompatible updates include a migration script that will make
the changes necessary for 4CAT to keep running, e.g. changing the database
structure.

This script runs those migration scripts, as needed, based on the current and
target version of 4CAT. It optionally also pulls the latest version of 4CAT
from Github and restarts the backend and frontend.
"""
import subprocess
import requests
import argparse
import shutil
import shlex
import time
import json
import sys
import os
import re

from pathlib import Path


def get_versions(target_version_file, current_version_file):
	"""
	Get versions

	:return tuple:  (target version readable, target version comparable, current version r, current version c)
	"""
	if not current_version_file.exists():
		# this is the latest version lacking version files
		current_version = "1.9"
	else:
		with current_version_file.open() as handle:
			current_version = re.split(r"\s", handle.read())[0].strip()

	if not target_version_file.exists():
		print("No VERSION file available. Cannot determine what version to migrate to.\n")
		exit(1)

	with target_version_file.open() as handle:
		target_version = re.split(r"\s", handle.read())[0].strip()

	current_version_c = make_version_comparable(current_version)
	target_version_c = make_version_comparable(target_version)

	return (target_version, target_version_c, current_version, current_version_c)


def make_version_comparable(version):
	"""
	Make a version comparable with normal operators

	:param str version:
	:return str:
	"""
	version = version.strip().split(".")
	return version[0].zfill(3) + "." + version[1].zfill(3)


cli = argparse.ArgumentParser()
cli.add_argument("--yes", "-y", default=False, action="store_true", help="Answer 'yes' to all prompts")
cli.add_argument("--pull", "-p", default=False, action="store_true", help="Pull and check out the latest 4CAT master branch commit from Github before migrating")
cli.add_argument("--release", "-l", default=False, action="store_true", help="Pull and check out the latest 4CAT release from Github before migrating")
cli.add_argument("--repository", "-r", default="https://github.com/digitalmethodsinitiative/4cat.git", help="URL of the repository to pull from")
cli.add_argument("--restart", "-x", default=False, action="store_true", help="Try to restart the 4CAT daemon after finishing migration, and 'touch' the WSGI file to trigger a front-end reload")
cli.add_argument("--current_version_location", "-v", default=".current-version", help="File path to .current_version file")
args = cli.parse_args()

print("")
if not Path(os.getcwd()).glob("4cat-daemon.py"):
	print("This script needs to be run from the same folder as 4cat-daemon.py\n")
	exit(1)

print("           4CAT migration agent           ")
print("------------------------------------------")
print("Interactive:             " + ("yes" if not args.yes else "no"))
print("Pull code from master:   " + ("yes" if args.pull else "no"))
print("Pull latest release:     " + ("yes" if args.release else "no"))
print("Restart after migration: " + ("yes" if args.restart else "no"))
print("Repository URL:          " + args.repository)
print("Version file:            " + args.current_version_location)

# ---------------------------------------------
#      Try to stop 4CAT if it is running
# ---------------------------------------------
interpreter = sys.executable

print("\nWARNING: Migration can take quite a while. 4CAT will not be available during migration.")
print("If 4CAT is still running, it will be shut down now (forcibly if necessary).")

if not args.yes:
	print("  Do you want to continue [y/n]? ", end="")
	if input("").lower() != "y":
		exit(0)

if not Path("backend/4cat.pid").exists():
	print("- No PID file found, assuming 4CAT is not running")
else:
	print("- Making sure 4CAT is stopped... ")
	result = subprocess.run([interpreter, "4cat-daemon.py", "--no-version-check", "force-stop"], stdout=subprocess.PIPE,
							stderr=subprocess.PIPE)
	if result.returncode != 0:
		print("  ...could not shut down 4CAT. Please make sure it is stopped and re-run this script.")
		print(result.stdout.decode("utf-8"))
		print(result.stderr.decode("utf-8"))
		exit(1)
	print("  ...done")

# ---------------------------------------------
#   Pull latest version of 4CAT from git repo
# ---------------------------------------------
if args.pull and not args.release:
	print("- Pulling latest commit from git repository %s..." % args.repository)
	command = "git pull %s master" % args.repository
	result = subprocess.run(shlex.split(command), stdout=subprocess.PIPE,
						stderr=subprocess.PIPE)

	if result.returncode != 0:
		print("Error while pulling latest version with git. Check that the repository URL is correct.")
		print(result.stderr.decode("ascii"))
		exit(1)

	if "Already up to date" in str(result.stdout):
		print("  ...latest version is already checked out.")
	else:
		print(result.stdout.decode("ascii"))

	print("  ...done\n")

# ---------------------------------------------
#     Determine current and target versions
# ---------------------------------------------
target_version_file = Path("VERSION")
current_version_file = Path(args.current_version_location)
target_version, target_version_c, current_version, current_version_c = get_versions(target_version_file, current_version_file)

migrate_to_run = []

# ---------------------------------------------
#          Check out latest release
# ---------------------------------------------
if args.release:
	print("- Pulling latest release from git repository %s..." % args.repository)
	repo_id = "/".join(args.repository.split("/")[-2:]).split(".git")[0]
	api_url = "https://api.github.com/repos/%s/releases/latest" % repo_id

	try:
		tag = requests.get(api_url, timeout=5).json()["tag_name"]
		print("  ...latest release is tagged %s." % tag)
	except (requests.RequestException, json.JSONDecodeError, KeyError):
		print("Error while retrieving latest release tag via GitHub API. Check that the repository URL is correct.")
		exit(1)

	tag_version = make_version_comparable(re.sub(r"^v", "", tag))
	if tag_version <= current_version_c:
		print("Latest release available from GitHub (%s) is older than or equivalent to currently checked out version "
			  "(%s)." % (tag_version, current_version_c))
		print("Cannot upgrade code, halting.")
		exit(1)

	tag_ref = shlex.quote("refs/tags/" + tag)
	command = "git fetch %s %s" % (args.repository, tag_ref)
	result = subprocess.run(shlex.split(command), stdout=subprocess.PIPE,
						stderr=subprocess.PIPE, cwd=os.getcwd())

	if result.returncode != 0:
		print("Error while pulling latest release with git. Check that the repository URL is correct.")
		print(result.stderr.decode("ascii"))
		exit(1)

	command = "git checkout --force %s" % tag_ref
	result = subprocess.run(shlex.split(command), stdout=subprocess.PIPE,
						stderr=subprocess.PIPE, cwd=os.getcwd())

	if result.returncode != 0:
		print("Error while checking out tag %s with git. Check that the repository URL is correct." % tag)
		print(result.stderr.decode("ascii"))
		exit(1)

	if "Already up to date" in str(result.stdout):
		print("  ...latest release is already checked out.")
	else:
		print(result.stdout.decode("ascii"))

	print("  ...done\n")

	# versions might have changed!
	target_version, target_version_c, current_version, current_version_c = get_versions(target_version_file, current_version_file)

# ---------------------------------------------
#                Start migration
# ---------------------------------------------
print("- Version last migrated to: %s" % current_version)
print("- Code version: %s" % target_version)

if current_version == target_version:
	print("Already up to date.\n")
	exit(0)

if current_version_c[0:3] != target_version_c[0:3]:
	print("Cannot migrate between different major versions.\n")
	exit(1)

if current_version_c > target_version_c:
	print("Checked out version is older than version last migrated to. Cannot migrate to older version.\n")
	print("WARNING: 4CAT may not function correctly. Consider re-installing.")
	exit(1)

# ---------------------------------------------
#      Collect relevant migration scripts
# ---------------------------------------------
migrate_files = Path(".").glob("helper-scripts/migrate/migrate-*.py")
for file in migrate_files:
	migrate_minimum = make_version_comparable(file.stem.split("-")[1])
	migrate_target = make_version_comparable(file.stem.split("-")[2])

	if migrate_minimum >= current_version_c and migrate_target <= target_version_c:
		migrate_to_run.append(file)

if not migrate_to_run:
	print("- No migration scripts to run.")
else:
	# oldest versions first
	migrate_to_run = sorted(migrate_to_run, key=lambda x: make_version_comparable(x.stem.split("-")[1]))

	print("- The following migration scripts will be run:")
	for file in migrate_to_run:
		print("  - %s" % file.name)

# ---------------------------------------------
#                    Run pip
# ---------------------------------------------
print("- Running pip to install any new dependencies (this could take a moment)...")
try:
	pip = subprocess.check_call([interpreter, "-m", "pip", "install", "-r", "requirements.txt"])
except subprocess.CalledProcessError as e:
	print(e)
	print("\n  Error running pip. You may need to run this script with elevated privileges (e.g. sudo).\n")
	exit(1)
print("  ...done")

# ---------------------------------------------
#       Run individual migration scripts
# ---------------------------------------------
if migrate_to_run:
	print("\n- Starting migration...")
	print("  %i scripts will be run." % len(migrate_to_run))

for file in migrate_to_run:
	file_target = file.stem.split("-")[2]
	print("- Migrating to %s via %s..." % (file_target, file.name))
	time.sleep(0.25)
	try:
		result = subprocess.run([interpreter, str(file.resolve())], stderr=subprocess.PIPE)
		if result.returncode != 0:
			raise RuntimeError(result.stderr.decode("utf-8"))
	except Exception as e:
		print("\n  Unexpected error while running %s. Migration halted." % file.name)
		print("  The following exception occurred:\n")
		print(e)
		print("\n")
		exit(1)
	print("  ...done")

	print("- Storing intermediate version file...")
	with current_version_file.open("w") as output:
		output.write(file_target)

# ---------------------------------------------
#            Update version data
# ---------------------------------------------
print("- Copying VERSION...")
if current_version_file.exists():
	current_version_file.unlink()
shutil.copy(target_version_file, args.current_version_location)
print("  ...done")


# ---------------------------------------------
#        Check for and install packages
# ---------------------------------------------
# NLTK
import nltk
try:
	nltk.data.find('tokenizers/punkt')
except LookupError:
	nltk.download('punkt')
try:
	nltk.data.find('corpora/wordnet')
except LookupError:
	nltk.download("wordnet")

print("\n- Migration scripts finished.")
print("  It is recommended to re-generate your Sphinx configuration and index files to account for database updates.")
print("  You can now safely restart 4CAT.\n")

if args.restart:
	print("- Triggering a WSGI reload by touching 4cat.wsgi...")
	Path("webtool/4cat.wsgi").touch()

	print("- Trying to restart daemon...")
	result = subprocess.run([interpreter, "4cat-daemon.py", "start"], stdout=subprocess.PIPE,
							stderr=subprocess.PIPE)

	if "error" in result.stdout.decode("utf-8"):
		print("Could not start 4CAT daemon. Please inspect the error message and restart it manually:\n")
		print(result.stdout.decode("utf-8"))
		print(result.stderr.decode("ascii"))
		exit(1)
	else:
		print("  ...done.")
