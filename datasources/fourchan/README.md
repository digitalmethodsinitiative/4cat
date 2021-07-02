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
		"autoscrape": True  # automatically start scraping when 4CAT is started
	}
}
```

## Full-text search
This data source also requires a full-text search engine to allow for keyword
search.  4CAT is currently compatible with the [Sphinx](https://sphinxsearch.com)
full-text search engine. We recommend using version 3.3.1 downloadable
[here](sphinxsearch.com/downloads/current). You should make sure this Sphinx instance
is running locally before enabling this data source.
Installing and running Sphinx:
1. [Download the Sphinx 3.3.1 source code](sphinxsearch.com/downloads/current).
2. Create a sphinx directory somewhere, e.g. in the directory of your 4CAT instance
`4cat/sphinx/`. In it, paste all the unzipped contents of the sphinx-3.3.1.zip file
you just downloaded (so that it's filled with the directories `api`, `bin`, etc.).
In the Sphinx directory, also create a folder called `data`, and in this `data`
directory, one called `binlog`.
3. Add a configuration file. You can generate one by running the `generate_sphinx_config.py`
script in the folder `helper-scripts.py`. After running it, a file called `sphinx.conf`
will appear in the `helper-scripts` directory. Copy-paste this file to the `bin` folder
in your Sphinx directory (in the case of the example above: `4cat/sphinx/bin/sphinx.conf`).
4. Generate indexes for the posts that you already collected (if you haven't run any
scrape yet, you can do this later). Generating indexes means Sphinx will create fast
lookup tables so words can be searched quickly. In your command line interface, navigate
to the `bin` directory of your Sphinx installation and run the command `indexer.exe --all`.
This should generate the indexes.
5. Finally, before executing any searches, make sure Sphinx is active by running
`searchd.exe` in your command line interface (once again within the `bin` folder).

On Windows, you might encounter the error `The code execution cannot proceed because
 ssleay32.dll was not found` ([see also this page](https://www.sqlshack.com/getting-started-with-sphinx-search-engine/)).
 This can be solved by downloading Sphinx version 3.1.1. and copy-pasting the following
 files from the 3.1.1. `bin` directory to your 3.3.1 `bin` directory:
- libeay32.dll
- msvcr120.dll
- ssleay32.dll


## Importing 4chan data from elsewhere
If you want to import 4chan data from elsewhere rather than (or in addition to)
scraping it yourself, two helper scripts are included in `/helper-scripts`:

* `scrape_fuuka.py` can be used to scrape posts from any FoolFuuka-based 4chan
  archive. The resulting JSON files can then be imported into the database with
  `import_json_folder`.
* `import_4plebs.py` can be used to import a data dump from 
  [4plebs](http://4plebs.org), a 4chan archive that publishes semi-annual data
  dumps for a number of large boards. 
* `import_dump.py` can be used to import csv [files dumped by the 4chan archive archived.moe](https://archive.org/details/archivedmoe_db_201908).