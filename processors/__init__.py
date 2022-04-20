"""
Data sources are a collection of workers, processors and interface elements that extend 4CAT to allow scraping,
processing and/or retrieving data for a given platform (such as Instagram, Reddit or Telegram). 4CAT has APIs that can
do most of the scaffolding around this for you so data source can be quite lightweight and mostly focus on retrieving
the actual data while 4CAT's back-end takes care of the scheduling, determining where the output should go, et cetera.
"""