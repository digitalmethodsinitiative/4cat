# This version (re-)introduces processors that use Selenium
# we can auto-configure these in some circumstances, which is done here.
import configparser
import shutil
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

# ---------------------------------------------------------------------------
#                        Are we running in Docker?
# ---------------------------------------------------------------------------
in_docker = False
notification = False
config_path = Path(__file__).parent.parent.parent.joinpath("config/config.ini")
if config_path.exists():
    config_reader = configparser.ConfigParser()
    config_reader.read(config_path)
    in_docker = config_reader["DOCKER"].getboolean("use_docker_config")

# ---------------------------------------------------------------------------
#     Try to detect if geckodriver/chromedriver/etc are already available
# ---------------------------------------------------------------------------
print("  Checking if browsers and drivers for Selenium are available")
selenium_path = config.get("selenium.selenium_executable_path", None)
if not selenium_path:
    # not set, try to find
    print("  - Web driver path not configured, trying to detect via PATH... ")
    chromedriver = shutil.which("chromedriver")
    geckodriver = shutil.which("geckodriver")
    if chromedriver and geckodriver:
        print(f"    found both geckodriver ({geckodriver}) and chromedriver ({chromedriver})")
    elif geckodriver:
        print(f"    found geckodriver at {geckodriver}")
    elif chromedriver:
        print(f"    found chromedriver at {chromedriver}")
    else:
        print("    no web driver found, cannot auto-configure Selenium-based processors. \n"
              "    Install Firefox and geckodriver, or Chrome and chromedriver, manually and \n"
              "    configure them in the 4CAT settings if you want to use the Selenium-based \n"
              "    processors.")

    if geckodriver or chromedriver:
        if geckodriver and chromedriver:
            # suck it Google!!!!
            print(f"  - Preferring Firefox, configuring with geckodriver")

        driver = geckodriver if geckodriver else chromedriver
        browser = "firefox" if geckodriver else "chrome"
        print(f"  - Assuming {browser} is installed, configuring Selenium-based processors")
        config.set_or_create_setting("selenium.selenium_executable_path", driver, raw=False)
        config.set_or_create_setting("selenium.browser", browser, raw=False)
        config.set_or_create_setting("selenium.installed", True, raw=False)
else:

    print(f"  - Yes (webdriver at {selenium_path}), nothing to configure.")