# Webpage Scraper

This data source uses [Selenium](https://selenium-python.readthedocs.io/) in combination with
a [Firefox webdriver](https://github.com/mozilla/geckodriver/releases) and Firefox for linux
to scrape the HTML source code.

By mimicing a person using an actual browser, this method results in source code that closer
resembles the source code an actual user receives when compared with simple HTML requests. It
will also render JavaScript that starts as soon as a url is retrieved by a browser.

## Scraping data
The scraper requires very little configuration; you only need to set the boards
to scrape. This can be done in 4CAT settings tab in the `DATASOURCES` configuration
variable:

```
# Data source configuration
DATASOURCES = {
	"url_scraper": {},
}
