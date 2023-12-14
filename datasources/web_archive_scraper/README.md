# Web Archive Scraper

Get HTML page source from Web Archive (web.archive.org) via the Selenium webdriver and Firefox browser.

This uses a modified version of the general url_scraper to specifically extract pages
from the Web Archive. It uses the urls provided and the date range to scrape archived
versions of the provied urls.

## Installing Selenium
For Selenium to work, it requires both a web browser to be installed such as
Google Chrome or Firefox as well as a corresponding webdriver (this acts as a
connector between selenium and the browser).

We have tested and develop these processors with Firefox and [Geckodriver](https://github.com/mozilla/geckodriver/releases),
but in principle you can use Chrome or Chromium and [ChromeDriver](https://chromedriver.chromium.org/).

### Docker installation
Docker has an installation script that automatically runs with you update the
Selenium settings on the 4CAT settings page.
1. Set the "Browser type" to `firefox` and the "Path to webdriver" to `/usr/local/bin/geckodriver`
2. Restart the 4CAT backend container `docker restart 4cat_backend` or click the restart button in the Docker Application

Docker will use the `docker/install_selenium.py` file to install the necessary
packages and you can use any activated datasources dependent on Selenium. Just
add the datasources as specified below.

## Scraping data
The scraper requires very little configuration; you only need to set the boards
to scrape. This can be done in 4CAT settings tab in the `DATASOURCES` configuration
variable:

```
# Data source configuration
DATASOURCES = {
	"web_archive_scraper": {},
}
