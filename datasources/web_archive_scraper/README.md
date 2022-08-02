# Web Archive Scraper

Get HTML page source from Web Archive (web.archive.org) via the Selenium webdriver and Firefox browser.

This uses a modified version of the general url_scraper to specifically extract pages
from the Web Archive. It uses the urls provided and the date range to scrape archived
versions of the provied urls.

## Scraping data
The scraper requires very little configuration; you only need to set the boards
to scrape. This can be done in 4CAT settings tab in the `DATASOURCES` configuration
variable:

```
# Data source configuration
DATASOURCES = {
	"web_archive_scraper": {},
}
