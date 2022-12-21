# For imageboard data sources,
# create an index on the basis of a thread's archived or deleted timestamps.
# This is used to quickly fetch the last few threads if they haven't been marked
# as inactive (i.e. archived or deleted). We need these to check the status of these
# threads after they've disappeared off the index.
import configparser
import subprocess
import shutil
import shlex
import sys
import os

from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "'/../..")
from common.lib.database import Database
from common.lib.logger import Logger

log = Logger(output=True)
import common.config_manager as config

db = Database(logger=log, dbname=config.get('DB_NAME'), user=config.get('DB_USER'), password=config.get('DB_PASSWORD'),
              host=config.get('DB_HOST'), port=config.get('DB_PORT'), appname="4cat-migrate")

# ---------------------------------------------
#     New format for data source settings
# ---------------------------------------------
datasources = config.get("DATASOURCES")
if type(datasources) is dict:
    print("  Migrating data source settings")
    new_datasources = list(datasources.keys())

    # 'customimport' and 'custom' have been replaced with 'upload'
    if ("custom" in new_datasources or "customimport" in new_datasources) and "upload" not in new_datasources:
        print("  - Enabling new 'upload' datasource because 'custom' or 'customimport' were enabled")
        new_datasources.append("upload")

    if "custom" in new_datasources:
        print("  - Disabling and deleting obsolete 'custom' datasource")
        folder = Path(config.get("PATH_ROOT"), "datasources/custom")
        if folder.exists():
            shutil.rmtree(folder)
        new_datasources.remove("custom")

    if "customimport" in new_datasources:
        print("  - Disabling and deleting obsolete 'customimport' datasource")
        folder = Path(config.get("PATH_ROOT"), "datasources/customimport")
        if folder.exists():
            shutil.rmtree(folder)
        new_datasources.remove("customimport")

    # migrate settings
    for platform in ("4chan", "8kun", "8chan"):
        for setting in ("boards", "no_scrape", "autoscrape", "interval"):
            if platform in datasources and datasources[platform].get(setting):
                print(f"  - Migrating setting {platform}.{setting}...")
                config.set_or_create_setting(platform.replace("4", "four").replace("8", "eight") + "." + setting,
                                             datasources[platform][setting], raw=False)

    for platform in ("dmi-tcat", "dmi-tcatv2"):
        for setting in ("instances",):
            if platform in datasources and datasources[platform].get(setting):
                print(f"  - Migrating setting {platform}.{setting}...")
                config.set_or_create_setting(platform + "." + setting, datasources[platform][setting], raw=False)

    print(f"  - Migrating data source-specific expiration settings...")
    expiration = {datasource: {"timeout": info["expire-datasets"], "allow_optout": False} for datasource, info in
                  datasources.items() if "expire-datasets" in info}
    config.set_or_create_setting("expire.datasources", expiration, raw=False)

    print("  - Updating DATASOURCES setting...")
    config.set_or_create_setting("4cat.datasources", new_datasources, raw=False)
    config.delete_setting("DATASOURCES")

print("  Deleting and migrating deprecated settings...")
if config.get("IMAGE_INTERVAL"):
    print("  - IMAGE_INTERVAL -> fourchan.image_interval")
    config.set_or_create_setting("fourchan.image_interval", config.get("IMAGE_INTERVAL", 60), raw=False)
    config.delete_setting("IMAGE_INTERVAL")

print("  - WARN_EMAILS, WARN_INTERVAL, image_downloader_telegram.MAX_NUMBER_IMAGES -> removed")
config.delete_setting("WARN_EMAILS")
config.delete_setting("WARN_INTERVAL")
config.delete_setting("image_downloader_telegram.MAX_NUMBER_IMAGES")

# ---------------------------------------------
#               Look for ffmpeg
# ---------------------------------------------
# this is for the new video processors which need ffmpeg to work
# if it can't be installed, 4CAT can still run and migrate can continue
# but the user will need to manually install it later
print("  Looking for ffmpeg executable...")
current_ffmpeg = config.get("video_downloader.ffmpeg-path", None)
if current_ffmpeg and shutil.which(current_ffmpeg):
    print(f"  - ffmpeg configured and found at {current_ffmpeg}, nothing to configure")
else:
    print("  - Checking if we are in Docker... ", end="")
    in_docker = False
    config_path = Path(__file__).parent.parent.parent.joinpath("config/config.ini")
    if config_path.exists():
        config_reader = configparser.ConfigParser().read(config_path)
        in_docker = config_reader["DOCKER"].getboolean("use_docker_config")
        print("yes" if in_docker else "no")
    else:
        print("no")

    ffmpeg = shutil.which(config.get("video_downloader.ffmpeg-path", "ffmpeg"))
    if ffmpeg:
        print(f"  - ffmpeg found at {ffmpeg}, storing as config setting video_downloader.ffmpeg-path")
        config.set_or_create_setting("video_downloader.ffmpeg-path", ffmpeg)
    elif in_docker:
        print("  - ffmpeg not found, detected Docker environment, installing via apt")
        ffmpeg_install = subprocess.run(shlex.split("apt install -y ffmpeg"), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if ffmpeg_install.returncode == 0:
            print("  - ffmpeg intalled with apt!")
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
