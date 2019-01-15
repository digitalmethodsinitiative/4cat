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
Runs a number of workers in parallel threads, that query a central job queue 
for jobs to do. Workers implement a `work()` method that e.g. queries the job
queue to look for specific types of jobs and completes those jobs.

Adding other types of workers can be done by adding python files to the 
`/workers` folder. If the files contain classes that descend `BasicWorker`, 
they will be added to the pool. All workers continuously loop their `work()` 
method, until their own `looping` property is set to false. This can be done 
from inside `work()` or by calling `abort()` on the worker.

The workers can be configured mainly through the following class properties:

- `max_workers`: Amount of workers of this type to run simultaneously
- `pause`: How long to wait between loops of `work()`
- `type`: This should be set to the job type this worker is supposed to 
  complete, or a descriptive keyword if the worker does not use jobs.

## Extras and tools
- `database.sql` contains the description of the database used by the backend. 
  Running it should set up your tables and indexes if they have not been added 
  yet. The SQL is automatically run by upon startup, so there is no need to
  create tables before running it for the first time. 
  
In the `extras` folder, you will find the following additional tools:

- `extras/import_dump.py` is a script that takes the path of a 
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