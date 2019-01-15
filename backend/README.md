# 4CAT Backend

Runs worker threads in which the magic happens:

- Scraping image board threads and posts
- Downloading images
- Scheduling the above
- Parsing and processing search requests

The backend is intended to be run as a daemon process. This is only possible on 
UNIX-like systems (e.g. Linux or MacOS). See the `4cat-daemon.py` script in the
parent folder for instructions on how to start and control the daemon

If you are using Windows, you can run `bootstrap.py` in this folder directly.

## What it does
Queries a central job queue for outstanding jobs, and starts workers compatible
with those jobs once any are available.

Workers should be in `datasources`, or the `workers` and `postprocessors` 
sub-folders of `backend`. Any Python files that contain classes extending (a 
subclass of) `BasicWorker` will be considered available for use in this way.
Such classes can be further configured with the following properties:

- `max_workers`: Amount of workers of this type to run simultaneously
- `type`: This should be set to the job type this worker is supposed to 
  complete

## Extras and tools
- `database.sql` contains the description of the database used by the backend. 
  Running it should set up your tables and indexes if they have not been added 
  yet. Note that data sources may define additional tables; each should have
  an additional `database.sql` file in its folder if that is the case.
  
In the `extras` folder, you will find the following additional tools:

- `extras/import_4chan.py` is a script that takes the path of a 
  [4plebs dump](https://archive.org/details/4plebs) as an  argument, and 
  inserts all posts and threads contained therein into the database. Dumps may
  be in CSV or SQLite format. Run the script without arguments for further 
  explanation:

  ```
  python3 import_dump.py
  ```

- `extras/munin_plugins` is a collection of python scripts that can be used as
  a plugin for [Munin](http://munin-monitoring.org), and query the local API to
  generate stats that are compatible with Munin's graphing.
  
- `extras/generate_sphinx.py` is a script that generates a Sphinx configuration
  file based on config settings and the data sources available.