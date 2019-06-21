# Architecture

4CAT consists of a number of separate components that together make it work. In 
the interest of maintainability, this document describes the high- to mid-level 
components of the 4CAT software.

## Backend
This is the 'heart' of 4CAT, which collects data, processes it, and saves it
for later retrieval.

### The manager
The manager (dispatcher, scheduler) maintains an overview of *worker* types
that are available, as well as a *queue* that it takes *jobs* from to hand
over to the *workers* for execution. This is the 'main loop' of the backend;
until a `SIGTERM` is received by the manager, it will infinitely loop, checking
the *queue* for *jobs* to hand to *workers*.

### The queue
The queue is, practically speaking, a database table in which *jobs* are 
stored. It also keeps track of the status of jobs; whether they have been
claimed for execution, how often execution has been attempted, and the time
at which they have been interacted with.

### The job
A job is a set of data that describes a 'unit of work'; some sort of task that
4CAT should execute, such as scraping a site, running an analysis, or starting
an API server. Jobs can be claimed by a *worker*, which marks them as such in
the queue. Jobs can only be claimed by one *worker* at a time. The data of a
job in practice corresponds to the parameters a *worker* of the same type as 
the job is run with.

After a job has been claimed, it can be released, which basically resets it, 
making it available for claiming again, and increasing the attempt counter of 
the job by one. It can also be finished, which removes it from the job queue
altogether, leaving no trace.

There is one exception to this. Jobs can have an 'interval' set; if this is the
case, they are not removed from the queue when finished, but the time at which
they were last claimed is marked, and they will only be considered eligible for
claiming again when the interval runs out, i.e. when the current time is 
greater than the time it was last claimed, plus the interval.

### The worker
The worker takes a *job*'s data and runs some kind of code based on those 
parameters. What it does with it is undefined; it also has a connection to the
database, so it may query the database and output data, or transform an
existing data file into another, or loop infinitely and listen for incoming
connections on a given port. The *manager* retains an overview of all running
workers and will tell them to stop executing when it itself is told to shut
down.

Workers have a type, an identifier that corresponds to a *job*'s type. This 
determines which *jobs* a given worker will be assigned. Each worker type has
an upper limit to the amount of instances of it that may run simultaneously.
Workers extend a base class, configure themselves via class attributes, and
contain at least one method `work()` that is called when 4CAT is read to
execute a job.

### The data set
A data set is a set of metadata for a data set that has been built or generated 
by 4CAT. Data sets have a unique identifier based on their parameters, and 
correspond to a given file on the disk that contains the data. When a data
set is first instantiated, that file does not exist yet. A *worker*, through 
a *job*, will take the  metadata to construct the file with, and then save it
to disk.

Data sets differ from *jobs* in that they are persistent: while a *job*'s data 
is deleted when finished, a data set remains on file, with all its metadata, so 
that next to the raw data set there is a record of the parameters through which
it was constructed. 

Data sets are constructed when someone uses the 4CAT web interface to queue a
search. In most cases, simultaneously a *job* will be queued to run the query,
containing the unique query key as metadata through which to fetch the query
parameters. In this way, one of their purposes is a 'bridge' between the 4CAT
back-end and front-end. Data sets are also created when a processor is run.

### The data source
A data source is a set of parameters and scrapers to collect and query data 
with. Usually, a data source will correspond to a given forum or site, e.g.
4chan or 8chan. It will contain a number of scrapers - which are *workers* -
that collect data from the source, and store it in the database.

The data source also contains a database definition which should be run prior
to activating the data source, so its data can be stored properly, as well as
a configuration file for the Sphinx search daemon that is used by 4CAT to run
*data sets*.

Finally, the data source contains a file defining methods through which the
data may be searched for a given search query.

### Processors
Processors are a special type of *worker* that take an existing data set and 
process it to produce a new one. As such, they always require a *data set*
to do their work. That *data set* then contains a reference to an earlier 
*data set*, (the 'parent') which will be used as input.

Processors are classes extending a base class that set a number of class
attributes for configuration, and contain at least one method `process()` that
is called when 4CAT is ready to run the processor. Usually, the method will 
read the result file of an earlier *query*, then process that data somehow, 
writing the result to the result file of its own *data set*. Like other
*workers*, they have a type and can set how many instances may be run
simultaneously.

## Front-end
4CAT serves a web interface via the Python-based Flask framework that can be
used to view, manipulate and download the data it scrapes and processes.

### The API
4CAT contains an API, which configures a number of endpoints that can be called
with various parameters to - in a nutshell - make the backend do things and
retrieve the results of those things. 4CAT automatically generates an OpenAPI-
compatible specification of its API, which may be called from the endpoint
`/api/openapi.json`.

### The tool
4CAT also serves a web tool, containing a query window, a result overview and 
an interface to download results through and run further analyses with. This
requires little further configuration, and is mostly straightforward in usage.
It is a Flask app, so ideally one would run it via a WSGI-compatible server
such as Apache.

### The access to the tool and API
Parts of 4CAT are by default not accessible without logging in. You can set it
to allow access from particular hostnames (e.g. your university's VPN) without
login; people accessing 4CAT from this hostname are identified as a general
'autologin' user. 

Some API endpoints require authentication with an access token. Tokens may be
generated by any user and by default are valid for one year after generation. 
The precise method of authentication is described in the OpenAPI specification.

Furthermore, many API endpoints are rate-limited. This rate limit may be 
ignored by people accessing the API from a whitelisted hostname; like the
'autologin', this can be used to lift restrictions from anyone using your 
university's VPN, for example.