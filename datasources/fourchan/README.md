# 4chan data source for 4CAT

This data source can be used to allow 4CAT users to interface with 4chan data.
Since 4chan's data is ephemeral, this data source includes a scraper to locally
store 4chan data.

Please follow the [installation instructions for local data sources](https://github.com/digitalmethodsinitiative/4cat/wiki/Enabling-local-data-sources) on the 4CAT GitHub to enable this data source.

## Scraping data
The scraper requires very little configuration; you only need to set the boards
to scrape. This can be done in the 4CAT settings panel.

## Full-text search
This data source also requires a full-text search engine to allow for keyword
search. 4CAT is currently compatible with the [Sphinx](https://sphinxsearch.com)
full-text search engine. See the [installation instructions for local data sources](https://github.com/digitalmethodsinitiative/4cat/wiki/Enabling-local-data-sources).

## Importing 4chan data from elsewhere
If you want to import 4chan data from elsewhere rather than (or in addition to)
scraping it yourself, various scripts in `/helper-scripts` allow to import external data:

* `scrape_fuuka.py` scrapes posts from any FoolFuuka-based 4chan
  archive, like 4plebs. The resulting JSON files can then be imported into the database with
  `import_json_folder`.
* `import_4plebs.py` imports data dumps from 
  [4plebs](http://4plebs.org), a 4chan archive that publishes semi-annual data
  dumps for a number of large boards. 
* `import_dump.py` imports [csv files dumped by the 4chan archive archived.moe](https://archive.org/details/archivedmoe_db_201908).
* `import_sqlite_dump.py` imports [4archived data](https://archive.org/download/4archive/4archive_dump-sqlite.7z).
* `import_4chan_csv.py` import data exported from another 4CAT instance.