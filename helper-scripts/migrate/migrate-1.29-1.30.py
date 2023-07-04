# For imageboard data sources,
# create an index on the basis of a thread's archived or deleted timestamps.
# This is used to quickly fetch the last few threads if they haven't been marked
# as inactive (i.e. archived or deleted). We need these to check the status of these
# threads after they've disappeared off the index.
import configparser
import subprocess
import shutil
import shlex
import json
import sys
import os

from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger
from common.lib.helpers import add_notification

log = Logger(output=True)

import configparser
ini = configparser.ConfigParser()
ini.read(Path(__file__).parent.parent.parent.resolve().joinpath("config/config.ini"))
db_config = ini["DATABASE"]

db = Database(logger=log, dbname=db_config["db_name"], user=db_config["db_user"], password=db_config["db_password"],
              host=db_config["db_host"], port=db_config["db_port"], appname="4cat-migrate")

def config_get(attribute, default=None):
    """
    Get config value

    We can't use config_get() here because in a later version it will become
    incompatible with the 1.29 database structure.

    :param attribute:
    :return:
    """
    v = db.fetchone("SELECT value FROM settings WHERE name = %s", (attribute, ))
    return v["value"] if v else default

def config_set(attribute, value):
    """
    Set config value

    We can't use config_set() here because in a later version it will become
    incompatible with the 1.29 database structure.

    :param attribute:
    :return:
    """
    return db.update("settings", where={"name": attribute}, data={"value": json.dumps(value)})

def delete_setting(attribute):
    return db.delete("settings", where={"name": attribute})

# ---------------------------------------------
#     New format for data source settings
# ---------------------------------------------
datasources = config_get("DATASOURCES")
if type(datasources) is dict:
    print("  Migrating data source settings")
    new_datasources = list(datasources.keys())

    # 'customimport' and 'custom' have been replaced with 'upload'
    if ("custom" in new_datasources or "customimport" in new_datasources) and "upload" not in new_datasources:
        print("  - Enabling new 'upload' datasource because 'custom' or 'customimport' were enabled")
        new_datasources.append("upload")

    if "custom" in new_datasources:
        print("  - Disabling and deleting obsolete 'custom' datasource")
        folder = Path(config_get("PATH_ROOT"), "datasources/custom")
        if folder.exists():
            shutil.rmtree(folder)
        new_datasources.remove("custom")

    if "customimport" in new_datasources:
        print("  - Disabling and deleting obsolete 'customimport' datasource")
        folder = Path(config_get("PATH_ROOT"), "datasources/customimport")
        if folder.exists():
            shutil.rmtree(folder)
        new_datasources.remove("customimport")

    # migrate settings
    for platform in ("4chan", "8kun", "8chan"):
        for setting in ("boards", "no_scrape", "autoscrape", "interval"):
            if platform in datasources and datasources[platform].get(setting):
                print(f"  - Migrating setting {platform}.{setting}...")
                config_set(platform.replace("4", "four").replace("8", "eight") + "." + setting,
                           datasources[platform][setting])

    for platform in ("dmi-tcat", "dmi-tcatv2"):
        for setting in ("instances",):
            if platform in datasources and datasources[platform].get(setting):
                print(f"  - Migrating setting {platform}.{setting}...")
                config_set(platform + "." + setting, datasources[platform][setting])

    print(f"  - Migrating data source-specific expiration settings...")
    expiration = {datasource: {"timeout": info["expire-datasets"], "allow_optout": False} for datasource, info in
                  datasources.items() if "expire-datasets" in info}
    config_set("expire.datasources", expiration)

    print("  - Updating DATASOURCES setting...")
    config_set("4cat.datasources", new_datasources)
    delete_setting("DATASOURCES")

print("  Deleting and migrating deprecated settings...")
config_set("4cat.phone_home_asked", False)
if config_get("IMAGE_INTERVAL"):
    print("  - IMAGE_INTERVAL -> fourchan.image_interval")
    config_set("fourchan.image_interval", config_get("IMAGE_INTERVAL", 60))
    delete_setting("IMAGE_INTERVAL")

print("  - WARN_EMAILS, WARN_INTERVAL, image_downloader_telegram.MAX_NUMBER_IMAGES -> removed")
delete_setting("WARN_EMAILS")
delete_setting("WARN_INTERVAL")
delete_setting("image_downloader_telegram.MAX_NUMBER_IMAGES")


# ---------------------------------------------
#         Check if Docker .env up to date
# ---------------------------------------------
in_docker = False
notification = False
config_path = Path(__file__).parent.parent.parent.joinpath("config/config.ini")
if config_path.exists():
    config_reader = configparser.ConfigParser()
    config_reader.read(config_path)
    in_docker = config_reader["DOCKER"].getboolean("use_docker_config")
    if in_docker:
        # Add notification if docker version in .env file is not updated
        # NOTE: this checks the COPIED .env file in the Docker container not the actual file used by Docker
        # It should still represent the version used when creating the Docker container, but if that file is updated and
        # container is not rebuilt AND migrate runs again, this message will be added again and may cause confusion.
        with open('.env') as f:
            for line in f.readlines():
                if "DOCKER_TAG" in line:
                    docker_version = line.split('=')[-1].strip()
                    if docker_version not in ['latest', 'stable']:
                        notification = f"You have updated 4CAT, but your Docker .env file indicates you installed a specific version. If you recreate your 4CAT Docker containers, 4CAT will regress to {docker_version}. Consider updating DOCKER_TAG in .env to the 'stable' tag to always use the latest version."
                        add_notification(db, "!admins", notification)
                    break


# ---------------------------------------------
#               Look for ffmpeg
# ---------------------------------------------
# this is for the new video processors which need ffmpeg to work
# if it can't be installed, 4CAT can still run and migrate can continue
# but the user will need to manually install it later
print("  Looking for ffmpeg executable...")
current_ffmpeg = config_get("video_downloader.ffmpeg-path", None)
if current_ffmpeg and shutil.which(current_ffmpeg):
    print(f"  - ffmpeg configured and found at {current_ffmpeg}, nothing to configure")
else:
    print("  - Checking if we are in Docker... ", end="")
    print("yes" if in_docker else "no")

    ffmpeg = shutil.which(config_get("video_downloader.ffmpeg-path", "ffmpeg"))
    if ffmpeg:
        print(f"  - ffmpeg found at {ffmpeg}, storing as config setting video_downloader.ffmpeg-path")
        config_set("video_downloader.ffmpeg-path", ffmpeg)
    elif in_docker:
        print("  - ffmpeg not found, detected Docker environment, installing via apt")
        ffmpeg_install = subprocess.run(shlex.split("apt install -y ffmpeg"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ffmpeg_install.returncode == 0:
            print("  - ffmpeg intalled with apt!")
            config_set("video_downloader.ffmpeg-path", shutil.which("ffmpeg"))
        else:
            print(f"  - Error while installing ffmpeg with apt (return code {ffmpeg_install.returncode}). Some video")
            print("    processors will be unavailable until you rebuild the Docker containers.")
            print("    apt output is printed below:")
            print(ffmpeg_install.stderr)
            print(ffmpeg_install.stdout)
    else:
        print("  - ffmpeg not found on system! Some video processors will not be available.")
        print("    Install ffmpeg and configure its path in the 4CAT General Settings to enable")
        print("    these.")

# ---------------------------------------------
#         Image board datasource updates
# ---------------------------------------------
print("  Creating new indexes for enabled imageboard datasources...")

imageboards_enabled = False

# remove obsolete data sources
to_delete = (Path())

# Check for 8kun
is_8kun = db.fetchone(
    "SELECT EXISTS ( SELECT FROM information_schema.tables WHERE table_name = %s )" % "'threads_8kun'")
if is_8kun["exists"]:
    imageboards_enabled = True

    print("  - Creating 'threads_archiving_8kun' index if it didn't exist already...")

    db.execute("""
        CREATE INDEX IF NOT EXISTS threads_archiving_8kun
          ON threads_8kun (
            timestamp_deleted, timestamp_archived, timestamp_modified, board
          );
    """)

    db.commit()

# Check for 4chan
is_4chan = db.fetchone(
    "SELECT EXISTS ( SELECT FROM information_schema.tables WHERE table_name = %s )" % "'threads_4chan'")
if is_4chan["exists"]:
    imageboards_enabled = True

    print("  - Creating 'threads_archiving_4chan' index if it didn't exist already...")
    db.execute("""
        CREATE INDEX IF NOT EXISTS threads_archiving_4chan
          ON threads_4chan (
            timestamp_deleted, timestamp_archived, timestamp_modified, board
          );
    """)

    db.commit()

if not imageboards_enabled:
    print("  - No imageboard data sources enabled")
else:
    print("  - Done!")

if notification:
    print("\nWARNING:" + notification + "\n")
