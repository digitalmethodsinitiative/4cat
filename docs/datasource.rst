=================
4CAT Data sources
=================

4CAT is a modular tool. Its modules come in two varieties: data sources and processors. This article covers the former.

Data sources are a collection of workers, processors and interface elements that extend 4CAT to allow scraping,
processing and/or retrieving data for a given platform (such as Instagram, Reddit or Telegram). 4CAT has APIs that can
do most of the scaffolding around this for you so data source can be quite lightweight and mostly focus on retrieving
the actual data while 4CAT's back-end takes care of the scheduling, determining where the output should go, et cetera.

Data sources are defined as an arbitrarily-named folder in the datasources folder in the 4CAT root. It is recommended to
use the datasource ID (see below) as the data source folder name. However, since Python files included in the folder
will be included as modules by 4CAT, folder names should be allowed as module names. Concretely this means (among other
things) that data source folder names cannot start with a number (hence the fourchan data source).

*WARNING:* Data sources in multiple ways can define arbitrary code that will be run by either the 4CAT server or
client-side browsers. Be careful when running a data source supplied by someone else.

A data source will at least contain the following:

* An __init__.py containing data source metadata and initialisation code
* A search worker, which can collect data according to provided parameters and format it as a CSV or NDJSON file that
  4CAT can work with.

It may contain additional components:

* Any processors that are specific to datasets created by this data source
* Views for the web app that allow more advanced behaviour of the web tool interface
* Database or Sphinx index definitions

The instructions below describe how to format and create these components (work in progress!)

-------------------
Initialisation code
-------------------

The data source root should contain a file `__init__.py` which in turn defines the following:

.. code-block:: python

    DATASOURCE = "datasource-identifier"

This constant defines the data source ID. This is most importantly used in config.py to enable the data source.

.. code-block:: python

    def init_datasource(database, logger, queue, name):
        pass

This function is called when 4CAT starts, if the data source is enabled, and should set up anything the data source
needs to function (e.g. queueing any recurring workers). A default implementation of this function can be used instead
(and when defining your own, it is advised to still call it as part of your own implementation):

.. code-block:: python

    from backend.lib.helpers import init_datasource

------------------
The `Search` class
------------------
.. autoclass:: backend.abstract.search.Search
    :members:
    :undoc-members:
    :show-inheritance:

---------------------------
The `SearchWithScope` class
---------------------------
.. autoclass:: backend.abstract.search.SearchWithScope
    :members:
    :undoc-members:
    :show-inheritance: