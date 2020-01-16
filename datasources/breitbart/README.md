# Breitbart data source for 4CAT

This data source can be used to allow a user to interface with a locally stored
database of comments. While it was created for and named after the Breitbart
news site, you could in principle use it for any locally stored corpus of 
threaded comments.

This datasource requires its own database tables. Run `database.sql` with 
4CAT's PostgreSQL user before enabling this dataset. Populating the database is
left as an exercise for the reader :-)

## Full-text search
This data source also requires a full-text search engine to allow for keyword
search. It is currently compatible with the [Sphinx](https://sphinxsearch.com)
full-text search engine. You should make sure a Sphinx instance is running 
locally before enabling this data source. `sphinx.conf` contains the relevant
index and source definitions for Sphinx; copy it to `sphinx.conf` and change 
the file paths and login details as required.

You can use `generate_sphinx.py` in the `/helper-scripts` folder to generate
a Sphinx configuration file that should work.