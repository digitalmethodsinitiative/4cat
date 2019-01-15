"""
Helper script to generate Sphinx configuration files with

If you use multiple data sources, keeping the Sphinx configuration up to date
can be tedious, and it can be beneficial to keep separate source configuration
files per data source. This script looks for "sphinx.conf" files in data source
folders that define Sphinx sources, and automatically generates index
definitions for them, after which it outputs a combined configuration file that
should be useable by Sphinx.

The "template" for this file is in 4cat-sphinx.conf.src (by default). It
contains general settings such as memory limits and also defines the defaults
for data sources and indexes that can (but do not have to) be overridden by
data source-specific sources.
"""
import importlib
import argparse
import glob
import sys
import os
import re

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../..")
import config


# parse parameters
cli = argparse.ArgumentParser()
cli.add_argument("-i", "--input", default="../../datasources", help="Folder to read data source data from")
cli.add_argument("-o", "--output", default="sphinx.conf", help="Filename of generated configuration file")
cli.add_argument("-s", "--source", default="4cat-sphinx.conf.src", help="Filename of configuration template")
args = cli.parse_args()

HOME = os.path.abspath(os.path.dirname(__file__))

os.chdir(HOME)
with open(args.source) as conffile:
	sphinxconf = "".join(conffile.readlines())

os.chdir(args.input)
confs = glob.glob("*/sphinx.conf")

sources = []
indexes = []

regex_source = re.compile(r"source ([^ ]+) : 4cat {([^}]+)}")

# go through all data sources found
for conf in confs:
	datasource = conf.split("/")[0]
	module = "datasources." + datasource

	# check if data source can be imported
	try:
		importlib.import_module(module)
	except ImportError:
		print("Error loading settings for data source %s. Skipping." % datasource)
		continue

	# check if imported data source has the required attribute (i.e. the platform identifier)
	try:
		platform = sys.modules[module].PLATFORM
	except AttributeError:
		print("Data source %s has no platform identifier set. Skipping." % datasource)
		continue

	with open(conf) as conffile:
		confsrc = "".join(conffile.readlines())

	defined_sources = regex_source.findall(confsrc)

	# parse found sources into index definitions
	for source in defined_sources:
		sources.append("source %s : 4cat {%s}" % source)
		name = source[0]
		index_name = platform + "_posts" if "posts" in name else platform + "_threads" if "threads" in name else False
		if not index_name:
			# we only know how to deal with post and thread sources
			print("Unrecognized data source %s. Skipping." % name)
			continue

		definition = source[1]
		index = """\nindex %s : 4cat_index {\n	source = %s\n	path = %s\n}""" % (index_name, name, config.SPHINX_PATH + "/" + index_name)
		indexes.append(index)

# write results to file
os.chdir(HOME)
sphinxconf = sphinxconf.replace("%%SOURCES%%", "\n".join(sources))
sphinxconf = sphinxconf.replace("%%INDEXES%%", "\n".join(indexes))
sphinxconf = sphinxconf.replace("%%DATADIR%%", config.SPHINX_PATH)

sphinxconf = sphinxconf.replace("%%DBLOCATION%%", str(config.DB_HOST))
sphinxconf = sphinxconf.replace("%%DBUSER%%", str(config.DB_USER))
sphinxconf = sphinxconf.replace("%%DBPASS%%", str(config.DB_PASSWORD))
sphinxconf = sphinxconf.replace("%%DBNAME%%", str(config.DB_NAME))
sphinxconf = sphinxconf.replace("%%DBPORT%%", str(config.DB_PORT))

with open(args.output, "w") as output:
	output.write(sphinxconf)