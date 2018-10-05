# 4CAT Backend

Runs worker threads in which the magic happens:

- Scraping 4chan threads and posts
- Downloading images
- Scheduling the above
- Parsing and processing search requests (todo!)

Run:

`python3 run.py`

Needs:

- `pip3 install requests psycopg2-binary` or `pip3 install -e requirements.txt`
- A PostgreSQL (>= 9.5) database and user with rights on that database (see 
  `config.py-example`)

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

## Additional tools
- `import_dump.py` is a script that takes the path of a 4plebs dump as an 
  argument, and inserts all posts and threads contained therein into the 
  database. Dumps may be in CSV or SQLite format. Run the script without 
  arguments for further explanation:

  `python3 importDump.py`
  
- `database.sql` contains the description of the database used by the backend. 
  Running it should set up your tables and indexes if they have not been added 
  yet. The SQL is automatically run by `run.py`, so there is no need to create
  tables before running it for the first time. 