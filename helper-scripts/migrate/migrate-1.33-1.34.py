"""
Move config.ini file from config/ to data/config

This is done in order to consolidate 4CAT data in particular as one Docker volume
"""
import os
import shutil
from pathlib import Path


print("  Checking if config.ini file needs to be moved...")

cwd = Path(os.getcwd())
new_config_file = cwd.joinpath("data/config/config.ini")

if not new_config_file.exists():
    # Ensure the new directory exists
    if not new_config_file.parent.is_dir():
        os.makedirs(new_config_file.parent)

    # Get old config_file
    old_config_file = cwd.joinpath("config/config.ini")

    if old_config_file.exists():
        # Collect old config paths
        from common.config_manager import ConfigManager
        print("  Loading old config.ini file")
        old_config_manager = ConfigManager("config/config.ini")

        if old_config_manager.USING_DOCKER or os.environ.get('AM_I_IN_A_DOCKER_CONTAINER', False):
            # docker_setup will create correct config.ini
            from docker.docker_setup import create_config_ini_file
            create_config_ini_file(new_config_file)

        else:
            # Not in Docker, move old config.ini
            print("  Moving old config.ini file to data/config/")
            old_config_file.rename(new_config_file)

            # Move restart lock file
            Path("config/restart.lock").rename("data/config/restart.lock")

        print("  Done!")

    else:
        # We're upgrading but there is no old config.ini file?!
        print("  No config.ini file found!")
        print("  Please edit data/config/config.ini-example and rename as config.ini")
        exit(1)

    # Check on .current-version file
    # If migrate.py is from before v1.34, it will copy the file of the old config/ path which is unhelpful
    target_version_file = cwd.joinpath("VERSION")
    new_current_version_file = cwd.joinpath("data/config/.current-version")
    if not new_current_version_file.exists():
        print("  Moving .current-version file")
        shutil.copy(target_version_file, new_current_version_file)

else:
    print("  ...no, nothing to update.")
