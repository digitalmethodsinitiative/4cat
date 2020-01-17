# 4CAT Backend

The backend is where the magic happens:

- Scheduling workers
- Parsing and processing search requests
- Various helper methods and classes

The backend is intended to be run as a daemon process. See the 
`4cat-daemon.py` script in the parent folder for instructions on how to start 
and control the daemon.

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
  