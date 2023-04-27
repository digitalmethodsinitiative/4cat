"""
MOVE FOLDERS TO data...
"""
import os
import sys
import shutil
from pathlib import Path
import importlib


def move_directory(source, destination):
    shutil.copytree(source, destination)
    # TODO: remove previous?


print("  Checking if config.ini file needs to be moved...")

cwd = Path(os.getcwd())
new_config_file = cwd.joinpath("data/config/config.ini")

if not new_config_file.exists():
    # Get old config_file
    old_config_file = cwd.joinpath("config/config.ini")

    if old_config_file.exists():
        # Collect old config paths
        from common.config_manager import ConfigManager
        old_config_manager = ConfigManager("config/config.ini")
        print("Loading old config.ini file")

        if old_config_manager.USING_DOCKER or os.environ.get('AM_I_IN_A_DOCKER_CONTAINER', False):

            # docker_setup will create correct config.ini
            from docker.docker_setup import create_config_ini_file
            create_config_ini_file(new_config_file)

            # Now config_manager can be imported as normal
            # Move data from previous paths
            importlib.reload(sys.modules['common.config_manager'])
            import common.config_manager as new_config_manager

            # We move all the old data to the new data structure (which all should exist in one directory/volume)
            if old_config_manager.PATH_DATA != new_config_manager.get("PATH_DATA"):
                print("  Moving datasets")
                move_directory(old_config_manager.PATH_ROOT.joinpath(old_config_manager.PATH_DATA), new_config_manager.get("PATH_ROOT").joinpath(new_config_manager.get("PATH_DATA")))

            if old_config_manager.PATH_IMAGES != new_config_manager.get("PATH_IMAGES"):
                print("  Moving images")
                move_directory(old_config_manager.PATH_ROOT.joinpath(old_config_manager.PATH_IMAGES), new_config_manager.get("PATH_ROOT").joinpath(new_config_manager.get("PATH_IMAGES")))

            if old_config_manager.PATH_LOGS != new_config_manager.get("PATH_LOGS"):
                print("  Moving logs")
                move_directory(old_config_manager.PATH_ROOT.joinpath(old_config_manager.PATH_LOGS), new_config_manager.get("PATH_ROOT").joinpath(new_config_manager.get("PATH_LOGS")))

            if old_config_manager.PATH_SESSIONS != new_config_manager.get("PATH_SESSIONS"):
                print("  Moving sessions")
                move_directory(old_config_manager.PATH_ROOT.joinpath(old_config_manager.PATH_SESSIONS), new_config_manager.get("PATH_ROOT").joinpath(new_config_manager.get("PATH_SESSIONS")))

            # TODO: Postgres database is still all on its own...

            print("  Done!")
        else:
            # Not in Docker, DO NOT move any files
            # Move old config.ini
            old_config_file.rename(new_config_file)


    else:
        # We're upgrading but there is no old config.ini file?!
        print("  No config.ini file found!")
        print("  Please edit config/config.ini-example, rename as config.ini, and move to data/config/")

    # Check on .current-version file
    # If migrate.py is from before v1.34, it will copy the file of the old config/ path which is unhelpful
    target_version_file = cwd.joinpath("VERSION")
    new_current_version_file = cwd.joinpath("data/config/.current-version")
    if not new_current_version_file.exists():
        print("  Moving .current-version file")
        shutil.copy(target_version_file, new_current_version_file)

else:
    print("  ...no, nothing to update.")
