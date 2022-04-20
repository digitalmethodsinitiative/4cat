===============
4CAT Processors
===============

4CAT is a modular tool. Its modules come in two varieties: data sources and processors. This article covers the latter.

Processors are bits of code that produce a dataset. Typically, their input is another dataset. As such they can be used
to analyse data; for example, a processor can take a csv file containing posts as input, count how many posts occur per
month, and produce another csv file with the amount of posts per month (one month per row) as output. Processors always
produce the following things:

* A set of metadata for the Dataset the processor will produce. This is stored in 4CAT's PostgreSQL database. The
  record for the database is created when the processor's job is first queued, and updated by the processor.
* A result file, which may have an arbitrary format. This file contains whatever the processor produces, e.g. a list
  of frequencies, an image wall or a zip archive containing word embedding models.
* A log file, with the same file name as the result file but with a '.log' extension. This documents any output from
  the processor while it was producing the result file.

4CAT has an API that can do most of the scaffolding around this for you so processors can be quite lightweight and
mostly focus on the analysis while 4CAT's back-end takes care of the scheduling, determining where the output should
go, et cetera.

A minimal example of a processor could look like this:

.. code-block:: python

    """
    A minimal example 4CAT processor
    """
    from backend.abstract.processor import BasicProcessor

    class ExampleProcessor(BasicProcessor):
        """
        Example Processor
        """
        type = "example-processor"  # job type ID
        category = "Examples" # category
        title = "A simple example"  # title displayed in UI
        description = "This doesn't do much"  # description displayed in UI
        extension = "csv"  # extension of result file, used internally and in UI

        input = "csv:body"
        output = "csv:value"

        def process(self):
            """
            Saves a CSV file with one column ("value") and one row with a value ("Hello
            world") and marks the dataset as finished.
            """
            data = {"value": "Hello world!"}
            self.write_csv_items_and_finish(data)



Module contents
---------------

.. mdinclude:: ../../processors/README.md


.. automodule:: processors
   :members:
   :undoc-members:
   :show-inheritance:


Subpackages
-----------

.. toctree::
   :maxdepth: 4

   processors.conversion
   processors.filtering
   processors.metrics
   processors.networks
   processors.presets
   processors.text_analysis
   processors.visualisation

