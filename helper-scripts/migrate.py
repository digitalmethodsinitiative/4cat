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
import logging
import shutil
import shlex
import time
import json
import sys
import os
import re

from pathlib import Path

class MigrationError(Exception):
    """Custom exception for migration errors."""
    pass

class FinishMigration(Exception):
    """A sepcial custom exception for to complete migration without errors."""
    pass

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
        raise MigrationError("Target version file does not exist.")

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


def check_for_nltk(logger):
    # ---------------------------------------------
    #        Check for and install packages
    # ---------------------------------------------
    # NLTK
    import nltk
    try:
        nltk.data.find('tokenizers/punkt_tab')
    except LookupError:
        logger.info("Downloading NLTK punkt data...")    
        nltk.download('punkt_tab', quiet=True)
    try:
        nltk.data.find('corpora/wordnet')
    except LookupError:
        logger.info("Downloading NLTK wordnet data...")    
        nltk.download("wordnet", quiet=True)
    
	# nltk.data.find('corpora/omw-1.4') does not appear to work
    nltk.download("omw-1.4", quiet=True)

def install_extensions(logger, no_pip=True):
    """
    Check for extensions and run any installation scripts found.

    Note: requirements texts are handled by setup.py
    """
    # Check for extension packages
    if os.path.isdir("extensions"):
        for root, dirs, files in os.walk("extensions"):
            for file in files:
                if file == "fourcat_install.py":
                    command = [interpreter, os.path.join(root, file)]
                    if args.component == "frontend":
                        command.append("--component=frontend")
                    elif args.component == "backend":
                        command.append("--component=backend")
                    elif args.component == "both":
                        command.append("--component=both")

                    if no_pip:
                        command.append("--no-pip")

                    logger.info(f"Installing extension: {os.path.join(root, file)}")
                    result = subprocess.run(command, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE)
                    if result.returncode != 0:
                        logger.error("Error while running extension installation script: " + os.path.join(root, file))

                    logger.info(result.stdout.decode("utf-8")) if result.stdout else None
                    logger.error(result.stderr.decode("utf-8")) if result.stderr else None


def finish(args, logger, no_pip=True):
    """
    Finish migration

    We might want to finish without running everything in the migration, so
    this is made a function that can be called from any point in the script to
    wrap up and exit.
    """
    check_for_nltk(logger)
    install_extensions(logger, no_pip=no_pip)
    logger.info("\nMigration finished. You can now safely restart 4CAT.\n")

    if args.restart:
        logger.info("- Trying to restart daemon...")
        result = subprocess.run([sys.executable, "4cat-daemon.py", "start"], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)

        if "error" in result.stdout.decode("utf-8"):
            logger.info("Could not start 4CAT daemon. Please inspect the error message and restart it manually:\n")
            logger.info(result.stdout.decode("utf-8"))
            logger.info(result.stderr.decode("ascii"))
            raise MigrationError("Failed to restart 4CAT daemon.")
        else:
            logger.info("  ...done.")
    
    # this is a special exception that is used to finish migration without errors
    raise FinishMigration("Finished migration without errors.")


cli = argparse.ArgumentParser()
cli.add_argument("--yes", "-y", default=False, action="store_true", help="Answer 'yes' to all prompts")
cli.add_argument("--release", "-l", default=False, action="store_true", help="Pull and check out the latest 4CAT release from Github before migrating")
cli.add_argument("--repository", "-r", default="https://github.com/digitalmethodsinitiative/4cat.git", help="URL of the repository to pull from")
cli.add_argument("--restart", "-x", default=False, action="store_true", help="Try to restart the 4CAT daemon after finishing migration, and 'touch' the WSGI file to trigger a front-end reload")
cli.add_argument("--no-migrate", "-m", default=False, action="store_true", help="Do not run scripts to upgrade between minor versions. Use if you only want to use migrate to e.g. upgrade dependencies.")
cli.add_argument("--current-version", "-v", default="config/.current-version", help="File path to .current-version file, relative to the 4CAT root")
cli.add_argument("--output", "-o", default="", help="By default migrate.py will send output to stdout. If this argument is set, it will write to the given path instead.")
cli.add_argument("--component", "-c", default="both", help="Which component of 4CAT to migrate ('both', 'backend', 'frontend'). Skips check for if 4CAT is running when set to 'frontend'. Also used by extensions w/ fourcat_install.py")
cli.add_argument("--branch", "-b", default=False, help="Which branch to check out from GitHub. By default, check out the latest release.")
args = cli.parse_args()

def main():
    """
    Main function to handle migration logic with error handling and cleanup.
    """
    exit_code = 0  # Default exit code
    error = None  # Initialize error frame
    try:
        print("")
        cwd = Path(os.getcwd())
        if not cwd.glob("4cat-daemon.py"):
            print("This script needs to be run from the same folder as 4cat-daemon.py\n")
            raise MigrationError("Script not run from the correct folder.")

        # track pip
        pip_ran = False

        # set up logging
        logger = logging.getLogger("migrate")
        logger.setLevel(logging.INFO)
        if args.output:
            # Add *only* a file handler if output is set
            # i.e. script will not output to stdout!
            handler = logging.FileHandler(args.output)
        else:
            handler = logging.StreamHandler(sys.stdout)
        logger.addHandler(handler)

        logger.info("           4CAT migration agent           ")
        logger.info("------------------------------------------")
        logger.info("Interactive:             " + ("yes" if not args.yes else "no"))
        logger.info("Pull latest release:     " + ("yes" if args.release else "no"))
        logger.info("Pull branch:             " + (args.branch if args.branch else "no"))
        logger.info("Restart after migration: " + ("yes" if args.restart else "no"))
        logger.info("Repository URL:          " + args.repository)
        logger.info(".current-version path:   " + args.current_version)
        logger.info(f"Current Datetime:        {time.strftime('%Y-%m-%d %H:%M:%S')}")

        # ---------------------------------------------
        #    Ensure existence of current version file
        # ---------------------------------------------
        target_version_file = cwd.joinpath("VERSION")
        current_version_file = cwd.joinpath(args.current_version)
        if not current_version_file.exists() and cwd.joinpath(".current-version").exists():
            logger.info("Moving .current-version to new location")
            cwd.joinpath(".current-version").rename(current_version_file)

        if not current_version_file.exists():
            logger.info("Creating .current-version file ")
            shutil.copy(target_version_file, current_version_file)

        # ---------------------------------------------
        #      Try to stop 4CAT if it is running
        # ---------------------------------------------
        interpreter = sys.executable

        # this sleep is here to give anything automating migrate the chance to keep up
        time.sleep(2)

        logger.info("\nWARNING: Migration can take quite a while. 4CAT will not be available during migration.")
        logger.info("If 4CAT is still running, it will be shut down now (forcibly if necessary).")

        if not args.yes:
            print("  ...do you want to continue [y/n]? ", end="")
            if input("").lower() != "y":
                return

        if not cwd.joinpath("backend/4cat.pid").exists():
            logger.info("\n- No PID file found, assuming 4CAT is not running")
        elif args.component == "frontend":
            logger.info("  ...updating front-end only, skipping check if daemon is running")
        else:
            logger.info("- Making sure 4CAT is stopped... ")
            result = subprocess.run([interpreter, "4cat-daemon.py", "--no-version-check", "force-stop"], stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, cwd=cwd)
            if result.returncode != 0:
                logger.info("  ...could not shut down 4CAT. Please make sure it is stopped and re-run this script.")
                logger.info(result.stdout.decode("utf-8"))
                logger.info(result.stderr.decode("utf-8"))
                raise MigrationError("Failed to stop 4CAT.")
            logger.info("  ...done")

        # ---------------------------------------------
        #     Determine current and target versions
        # ---------------------------------------------
        target_version, target_version_c, current_version, current_version_c = get_versions(target_version_file, current_version_file)
        migrate_to_run = []

        # ---------------------------------------------
        #          Check out latest release
        # ---------------------------------------------
        if args.release or args.branch:
            logger.info("- Interfacing with git repository %s..." % args.repository)
            if args.repository[:4] == "git@":
                repo_id = "/".join(args.repository.split(":")[1].split("/")[-2:]).split(".git")[0]
            else:
                repo_id = "/".join(args.repository.split("/")[-2:]).split(".git")[0]

            api_url = "https://api.github.com/repos/%s/releases/latest" % repo_id

            if args.release:
                try:
                    tag = requests.get(api_url, timeout=5).json()["tag_name"]
                    logger.info("  ...latest release is tagged %s." % tag)
                except (requests.RequestException, json.JSONDecodeError, KeyError):
                    logger.info("Error while retrieving latest release tag via GitHub API. Check that the repository URL is correct.")
                    raise MigrationError("Failed to retrieve latest release tag.")

                tag_version = make_version_comparable(re.sub(r"^v", "", tag))
                if tag_version <= current_version_c:
                    logger.info("  ...latest release available from GitHub (%s) is older than or equivalent to currently checked out version "
                          "(%s)." % (tag_version, current_version_c))
                    logger.info("  ...upgrade not necessary, skipping.")
                    finish(args, logger, no_pip=pip_ran)

            logger.info("  ...ensuring repository %s is a known remote" % args.repository)
            remote = subprocess.run(shlex.split("git remote add 4cat_migrate %s" % args.repository), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=cwd, text=True)
            if remote.stderr:
                if remote.stderr.strip() == "error: remote 4cat_migrate already exists.":
                    # Update URL
                    remote = subprocess.run(shlex.split("git remote set-url 4cat_migrate %s" % args.repository),
                                            stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, cwd=cwd, text=True)
                    if remote.stderr:
                        logger.info("Error while updating git remote for %s" % args.repository)
                        logger.info(remote.stderr)
                        raise MigrationError("Failed to update git remote.")
                else:
                    logger.info("Error while adding git remote for %s" % args.repository)
                    logger.info(remote.stderr)
                    raise MigrationError("Failed to add git remote.")

            logger.info("  ...fetching tags from repository")
            fetch = subprocess.run(shlex.split("git fetch 4cat_migrate"), stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=cwd, text=True)

            if fetch.returncode != 0:
                if "fatal: could not read Username" in fetch.stderr:
                    # git requiring login
                    from common.config_manager import config
                    if config.get("USING_DOCKER"):
                        # update git config setting
                        unset_authorization = subprocess.run(shlex.split("git config --unset http.https://github.com/.extraheader"), stderr=subprocess.PIPE, stdout=subprocess.PIPE, cwd=cwd, text=True)
                        fetch = subprocess.run(shlex.split("git fetch 4cat_migrate"), stderr=subprocess.PIPE,
                                               stdout=subprocess.PIPE, cwd=cwd, text=True)
                        if fetch.returncode != 0:
                            logger.info("Error while fetching latest tags with git. Check that the repository URL is correct.")
                            logger.info(fetch.stderr)
                            raise MigrationError("Failed to fetch latest tags.")
                else:
                    logger.info("Error while fetching latest tags with git. Check that the repository URL is correct.")
                    logger.info(fetch.stderr)
                    raise MigrationError("Failed to fetch latest tags.")

            if args.branch:
                logger.info(f"  ...checking out branch '{args.branch}'")
                command = f"git checkout --force 4cat_migrate/{args.branch}"
            else:
                logger.info("  ...checking out latest release")
                tag_ref = shlex.quote("refs/tags/" + tag)
                command = "git checkout --force %s" % tag_ref

            result = subprocess.run(shlex.split(command), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=cwd)

            if result.returncode != 0:
                if args.branch:
                    logger.info("Error while pulling latest release with git. Check that the repository URL and branch name are correct.")
                else:
                    logger.info("Error while pulling latest release with git. Check that the repository URL is correct.")
                logger.info(result.stderr.decode("ascii"))
                raise MigrationError("Failed to pull latest release.")

            if "Already up to date" in str(result.stdout):
                logger.info("  ...latest release is already checked out.")

            logger.info("  ...done")

            # versions might have changed!
            target_version, target_version_c, current_version, current_version_c = get_versions(target_version_file, current_version_file)

        # ---------------------------------------------
        #                Start migration
        # ---------------------------------------------
        logger.info("- Version last migrated to: %s" % current_version)
        logger.info("- Code version: %s" % target_version)

        if current_version == target_version:
            logger.info("  ...already up to date.")
            finish(args, logger, no_pip=pip_ran)

        if current_version_c[0:3] != target_version_c[0:3]:
            logger.info("  ...cannot migrate between different major versions.")
            raise MigrationError("Cannot migrate between different major versions.")

        if current_version_c > target_version_c:
            logger.info("  ...checked out version is older than version last migrated to. Cannot migrate to older version.")
            logger.info("WARNING: 4CAT may not function correctly. Consider re-installing.")
            raise MigrationError("Cannot migrate to older version.")

        # ---------------------------------------------
        #      Collect relevant migration scripts
        # ---------------------------------------------
        migrate_files = cwd.glob("helper-scripts/migrate/migrate-*.py")
        for file in migrate_files:
            migrate_minimum = make_version_comparable(file.stem.split("-")[1])
            migrate_target = make_version_comparable(file.stem.split("-")[2])

            if migrate_minimum >= current_version_c and migrate_target <= target_version_c:
                migrate_to_run.append(file)

        if not migrate_to_run:
            logger.info("- No migration scripts to run.")
        else:
            # oldest versions first
            migrate_to_run = sorted(migrate_to_run, key=lambda x: make_version_comparable(x.stem.split("-")[1]))

            logger.info("- The following migration scripts will be run:")
            for file in migrate_to_run:
                logger.info("  - %s" % file.name)

        # ---------------------------------------------
        #                    Install any needed packages
        # ---------------------------------------------

        try:
            from common.config_manager import config
        except ImportError:
            config = None

        if config and config.get("USING_DOCKER"):
            logger.info("- Running in Docker environment, checking for and installing any needed compilers...")
            # Pip needs some compilers to successfully update
            needed_packages = ["g++", "gcc"]
            try:
                apt_get = subprocess.run(["apt-get", "install", "-y"] + needed_packages, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
                logger.info("\n".join(["  " + line for line in apt_get.stdout.decode("utf-8").split("\n")]))
            except subprocess.CalledProcessError as e:
                logger.info("\n".join(["  " + line for line in e.output.decode("utf-8").split("\n")]))
                logger.info(f"\n Error while installing {needed_packages}: {e}")

        # ---------------------------------------------
        #                    Run pip
        # ---------------------------------------------
        def log_pip_output(logger, output):
            for line in output.decode("utf-8").split("\n"):
                if line.startswith("Requirement already satisfied:"):
                    # eliminate some noise in the output
                    continue
                logger.info("  " + line)

        logger.info("- Running pip to install new dependencies and upgrade existing dependencies")
        logger.info("  (this could take a moment)...")
        try:
            pip = subprocess.run([interpreter, "-m", "pip", "install", "-r", "requirements.txt", "--upgrade", "--upgrade-strategy", "eager"],
                                        stderr=subprocess.STDOUT, stdout=subprocess.PIPE, check=True, cwd=cwd)
            log_pip_output(logger, pip.stdout)
            pip_ran = True
        except subprocess.CalledProcessError as e:
            log_pip_output(logger, e.output)
            logger.info(f"\n Error running pip: {e}")
            raise MigrationError("Failed to run pip.")
        logger.info("  ...done")

        # ---------------------------------------------
        #       Run individual migration scripts
        # ---------------------------------------------
        if migrate_to_run:
            logger.info("\n- Starting migration...")
            logger.info("  %i scripts will be run." % len(migrate_to_run))

        for file in migrate_to_run:
            file_target = file.stem.split("-")[2]
            logger.info("- Migrating to %s via %s..." % (file_target, file.name))
            time.sleep(0.25)
            try:
                result = subprocess.run([interpreter, str(file.resolve())], stderr=subprocess.PIPE, cwd=cwd)
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.decode("utf-8"))
            except Exception as e:
                logger.info("\n  Unexpected error while running %s. Migration halted." % file.name)
                logger.info("  The following exception occurred:\n")
                logger.info(e)
                logger.info("\n")
                raise MigrationError("Migration halted due to an unexpected error.")
            logger.info("  ...done")

            logger.info("- Storing intermediate version file...")
            with current_version_file.open("w") as output:
                output.write(file_target)

        # ---------------------------------------------
        #            Update version data
        # ---------------------------------------------
        logger.info("- Copying VERSION...")
        if current_version_file.exists():
            current_version_file.unlink()
        shutil.copy(target_version_file, current_version_file)
        logger.info("  ...done")

        # ---------------------------------------------
        #            Done! Wrap up and finish
        # ---------------------------------------------
        finish(args, logger, no_pip=pip_ran)

    except MigrationError as e:
        # Handle migration-specific errors
        logging.error(f"Migration error: {e}")
        exit_code = 1
        error = e

    except FinishMigration as e:
        # Handle the special case of finishing migration without errors
        logging.info(f"Finished migration without errors: {e}")
        exit_code = 0
        
    except Exception as e:
        # Handle unexpected errors
        logging.error(f"An unexpected error occurred: {e}", exc_info=True)
        exit_code = 1
        error = e
        
    finally:
        # Try to import 4CAT's logger to send final log message of result
        # This has the benefit of the Slack webhook
        try:
            from common.lib.logger import Logger, SlackLogHandler
            log = Logger(logger_name='migrate-notify', filename='migrate.log')
            # Adjust the log level of the Slack handler
            for handler in log.logger.handlers:
                if isinstance(handler, SlackLogHandler):  # Check if it's the Slack handler
                    handler.setLevel(logging.INFO)  # Set the desired log level
            
            if exit_code == 0:
                log.info(f"Migration of {args.component} finished successfully.")
            else:
                import traceback
                error_stack = traceback.extract_tb(error.__traceback__) if error else None
                log.error(f"Migration {args.component}: {error}\nsee {args.output if args.output else 'stderr'}.", frame=error_stack)
        except ImportError:
            # If 4CAT's logger cannot be imported, fall back to the standard logger
            logger.error("Unable to import 4CAT log to inform about migration result.")

    sys.exit(exit_code)  # Exit after the finally block

# Entry point
if __name__ == "__main__":
    main()
