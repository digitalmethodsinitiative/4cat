# 4CAT Scraper

Run:

`python3 run.py`

Needs:

- `pip3 install requests psycopg2-binary`
- A PostgreSQL database and user with rights on
  that database.

## What it does
Runs a number of scrapers in parallel threads, that
query a central job queue for jobs to do. Jobs here
are objects to scrape, e.g. a board or a thread.

Adding other types of scrapers, or other types of job
processors, should be relatively little trouble. The 
scrape delay, and how many scrapers can be run in
parallel, can be configured via `config.py`.

As a proof of concept, some post data is saved into
the database, but this should be extended if this is
to actually scrape things.