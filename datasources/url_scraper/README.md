# Webpage Scraper

This data source uses [Selenium](https://selenium-python.readthedocs.io/) in combination with
a [Firefox webdriver](https://github.com/mozilla/geckodriver/releases) and Firefox for linux
to scrape the HTML source code.

By mimicing a person using an actual browser, this method results in source code that closer
resembles the source code an actual user receives when compared with simple HTML requests. It
will also render JavaScript that starts as soon as a url is retrieved by a browser.

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
	"url_scraper": {},
}
