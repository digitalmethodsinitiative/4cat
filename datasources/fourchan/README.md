# 4chan data source for 4CAT

This data source can be used to allow 4CAT users to interface with 4chan data.
Since 4chan has no API that is useful for 4CAT's purposes, this data source 
includes a scraper to locally store 4chan data for subsetting and manipulation.

As such, it requires its own database tables. Run `database.sql` with 4CAT's
PostgreSQL user before enabling this dataset.

## Scraping data
The scraper requires very little configuration; you only need to set the boards
to scrape. This can be done in `config.py` in the `DATASOURCES` configuration
variable:

```
# Data source configuration
DATASOURCES = {
	"4chan": {  # should correspond to DATASOURCE in the data source's __init__.py
		"interval": 60,  # scrape interval for boards
		"boards": ["pol", "v"], # boards to scrape (and generally make available)
	}
}
```

## Full-text search
This data source also requires a full-text search engine to allow for keyword
search. It is currently compatible with the [Sphinx](https://sphinxsearch.com)
full-text search engine. You should make sure a Sphinx instance is running 
locally before enabling this data source. `sphinx.conf` contains the relevant
index and source definitions for Sphinx; copy it to `sphinx.conf` and change 
the file paths and login details as required.

You can use `generate_sphinx.py` in the `/helper-scripts` folder to generate
a Sphinx configuration file that should work.

## Importing 4chan data from elsewhere
If you want to import 4chan data from elsewhere rather than (or in addition to)
scraping it yourself, two helper scripts are included in `/helper-scripts`:

* `scrape_fuuka.py` can be used to scrape posts from any FoolFuuka-based 4chan
  archive. The resulting JSON files can then be imported into the database with
  `queue_folder.py`.
* `import_4plebs.py` can be used to import a data dump from 
  [4plebs](http://4plebs.org), a 4chan archive that publishes semi-annual data
  dumps for a number of large boards. 