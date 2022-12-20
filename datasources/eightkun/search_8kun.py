"""
8kun Search via Sphinx
"""
from datasources.fourchan.search_4chan import Search4Chan

import common.config_manager as config
from common.lib.helpers import UserInput


class Search8Kun(Search4Chan):
	"""
	Search 8kun corpus

	Defines methods that are used to query the 8kun data indexed and saved.

	Apart from the prefixes, this works identically to the 4chan searcher, so
	most methods are inherited from there.
	"""
	type = "8kun-search"
	sphinx_index = "8kun"
	prefix = "8kun"
	is_local = True	# Whether this datasource is locally scraped
	is_static = False	# Whether this datasource is still updated

	options = {
		"intro": {
			"type": UserInput.OPTION_INFO,
			"help": "Results are limited to 5 million items maximum. Be sure to read the [query "
					"syntax](/page/query-syntax/) for local data sources first - your query design will "
					"significantly impact the results. Note that large queries can take a long time to complete!\n\n"
					"[8kun](https://8kun.top) is an image board that serves as a successor to 8chan. While it is "
					"virtually identical, it has a different owner and does not incorporate all of 8chan's board, in "
					"addition to offering new ones that did not exist on 8chan."
		},
		"board": {
			"type": UserInput.OPTION_CHOICE,
			"options": {b: b for b in config.get("eightkun.boards", [])},
			"help": "Board",
			"default": config.get("eightkun.boards", [""])[0]
		},
		"body_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Post contains"
		},
		"subject_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Subject contains"
		},
		"divider": {
			"type": UserInput.OPTION_DIVIDER
		},
		"daterange": {
			"type": UserInput.OPTION_DATERANGE,
			"help": "Date range"
		},
		"search_scope": {
			"type": UserInput.OPTION_CHOICE,
			"help": "Search scope",
			"options": {
				"posts-only": "All matching messages",
				"full-threads": "All messages in threads with matching messages (full threads)",
				"dense-threads": "All messages in threads in which at least x% of messages match (dense threads)"
			},
			"default": "posts-only"
		},
		"scope_density": {
			"type": UserInput.OPTION_TEXT,
			"help": "Min. density %",
			"min": 0,
			"max": 100,
			"default": 15,
			"tooltip": "At least this many % of messages in the thread must match the query"
		},
		"scope_length": {
			"type": UserInput.OPTION_TEXT,
			"help": "Min. dense thread length",
			"min": 30,
			"default": 30,
			"tooltip": "A thread must at least be this many messages long to qualify as a 'dense thread'"
		}
	}

	config = {
		"eightkun.boards": {
			"type": UserInput.OPTION_TEXT_JSON,
			"help": "Boards to index",
			"tooltip": "These boards will be scraped and made available for searching. Provide as a JSON-formatted "
					   "list of strings, e.g. ['pol', 'v'].",
			"default": "[]"
		}
	}
