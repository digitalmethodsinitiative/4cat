# Install and run 4CAT

## Overview
4CAT has two components, the backend and the web tool. These share some bits
of code and a configuration file but apart from that they run independently.
Communication between the two happens via a PostgreSQL database.


## Installation
### Requirements
It is recommended that you run 4CAT on a UNIX-like system (e.g. Linux or
MacOS). 4CAT further requires Python 3.7 (lower versions may work but are not
supported) and PostgreSQL 9.5.

### Instructions
Clone the repository somewhere:

```
git clone https://www.github.com/digitalmethodsinitiative/4cat.git
```

After cloning the repository, copy `config.py-example` to `config.py` and edit
the file to match your machine's configuration. The various options are
explained in the file itself:

```
cd 4cat
cp config.py-example config.py
```

Note that you need to create a database and database user yourself: this is
not handled by 4CAT. Upon first running the backend, it will create new tables
and indices in the database specified in `config.py`, so make sure the
configured database user has the rights to do so.

Next, install the dependencies. While in the 4CAT root folder, run pip:

```
pip3 install -r requirements.txt
```

You should now be set up to run 4CAT. It is recommended that you next run the
included test suite to make sure everything has been set up correctly and that
you can reach the 4chan API:

```
python3 -m unittest discover test
```

If everything tested successfully, you will see a message similar to the 
following:

```
.........ss..............x.x...............
----------------------------------------------------------------------
Ran 43 tests in 9.837s

OK (skipped=2, expected failures=2)
```

You can now run 4CAT.

## Running 4CAT
### Running the backend
The backend is run as a daemon that can be started and stopped using the
included `4cat-daemon.py` script:

```
python3 4cat-daemon.py start
```

Other valid arguments are `stop`, `restart` and `status`. Note that 4CAT was
made to run on a UNIX-like system and the above will not work on Windows. If
you want to use Windows you can run `bootstrap.py` in the `backend` folder, 
which will run the backend directly in the terminal (this is not recommended 
except for testing or development, and disabled on UNIX-like systems).

### Running the web tool
The web tool is a Flask app. It is recommended that you run the web tool as a
WSGI module: see the [Flask documentation](http://flask.pocoo.org/docs/1.0/deploying/) 
for more details. For testing and development, you can run the Flask app 
locally from the command line:

```
FLASK_APP=webtool/fourcat flask run
```

With the default configuration, you can now navigate to 
`http://localhost:5000` where you'll find the web tool that allows you to query
the database and create datasets.

## Acquiring data
4CAT is not very useful with an empty database. To fill it with 4chan data,
you can either import data from elsewhere or scrape 4chan yourself (or do 
both).

### Import 4chan data dumps from elsewhere
Included in the `backend` folder is `import_dump.py`. You can use this script
to import dumps from 4plebs (e.g. 
[these](https://archive.org/details/4plebs-org-data-dump-2018-01)). Run the
script without arguments for more information on its syntax. Note that for
larger boards, imports can take a long time to finish (multiple days). This is
due to the sheer size of the data sets, and because 4CAT needs full text 
indices to search through the data, which take relatively long to generate. A
faster hard drive helps.

### Scrape 4chan yourself
The 4CAT backend comes with a 4chan API scraper that can capture new posts
on 4chan as they are posted. You can configure which boards are to be scraped
in `config.py`. Note that the 4chan API has a rate limit and scraping too many
boards will probably make you hit that limit quite quickly. It is recommended
that you keep an eye on the backend log files when you first start scraping to
make sure you're getting all the data you want. You may add a list of proxies
in the configuration file: 4CAT will use a random proxy while scraping, which
will likely allow for more requests before you hit the rate limit.

If you decide to scrape 4chan, **it is recommended that you run the 4chan API
compatibility test regularly** to remain aware of any changes in the API
response. The test is located at `test/test_4chan_api.py`. If the 4chan API
response is compatible with 4CAT, the tests within will pass: if not, pay close
attention to *which* tests fail, and read the failure messages for more info
on what to do next.

```
python3 -m unittest test/test_4chan_api.py
```

## Separating the backend and web tool
While by default the web tool and backend run on the same server, you could set
things up so that they run on separate servers instead. Simply only start the 
backend on one server, and the frontend on the other. If you configure the
front end to connect to the database on another server (or vice versa), the 
backend and front end will be able to communicate.