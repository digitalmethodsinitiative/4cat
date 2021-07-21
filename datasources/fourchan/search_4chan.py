"""
4chan Search via Sphinx
"""
import warnings
import time

from pymysql import OperationalError, ProgrammingError
from pymysql.err import Warning as SphinxWarning

import config
from backend.lib.database_mysql import MySQLDatabase
from common.lib.helpers import UserInput
from backend.abstract.search import SearchWithScope
from common.lib.exceptions import QueryParametersException, ProcessorInterruptedException


class Search4Chan(SearchWithScope):
	"""
	Search 4chan corpus

	Defines methods that are used to query the 4chan data indexed and saved.
	"""
	type = "4chan-search"  # job ID
	sphinx_index = "4chan"  # prefix for sphinx indexes for this data source. Should usually match sphinx.conf
	prefix = "4chan"  # table identifier for this datasource; see below for usage

	# Columns to return in csv
	return_cols = ['thread_id', 'id', 'timestamp', 'body', 'subject', 'author', 'image_file', 'image_md5',
				   'country_name', 'country_code']

	# before running a sphinx query, store it here so it can be cancelled via
	# request_abort() later
	running_query = ""

	options = {
		"intro": {
			"type": UserInput.OPTION_INFO,
			"help": "Results are limited to 5 million items maximum. Be sure to read the [query "
					"syntax](/page/query-syntax/) for local data sources first - your query design will "
					"significantly impact the results. Note that large queries can take a long time to complete!"
		},
		"board": {
			"type": UserInput.OPTION_CHOICE,
			"options": {b: b for b in config.DATASOURCES[prefix].get("boards", [])},
			"help": "Board",
			"default": config.DATASOURCES[prefix].get("boards", [""])[0]
		},
		"body_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Post contains"
		},
		"subject_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Subject contains"
		},
		"country_name": {
			"type": UserInput.OPTION_MULTI_SELECT,
			"help": "Poster country",
			"board_specific": ["pol", "sp", "int"],
			"tooltip": "The IP-derived flag attached to posts. Can be an actual country or \"meme flag\". Leave empty for all.", 
			"options": {
				"Armenia|Albania|Andorra|Austria|Belarus|Belgium|Bosnia and Herzegovina|Bulgaria|Croatia|Cyprus|Czech Republic|Denmark|Estonia|Finland|France|Germany|Greece|Hungary|Iceland|Republic of Ireland|Italy|Kosovo|Latvia|Liechtenstein|Lithuania|Luxembourg|Republic of Macedonia|North Macedonia|Macedonia|Malta|Moldova|Monaco|Montenegro|Netherlands|The Netherlands|Norway|Poland|Portugal|Romania|Russia|San Marino|Serbia|Slovakia|Slovenia|Spain|Sweden|Switzerland|Turkey|Ukraine|United Kingdom|Vatican City": "European countries",
				"Afghanistan": "<span class='flag flag-af' title='Afghanistan'></span> Afghanistan",
				"Aland": "<span class='flag flag-ax' title='Aland'></span> Aland",
				"Albania": "<span class='flag flag-al' title='Albania'></span> Albania",
				"Algeria": "<span class='flag flag-dz' title='Algeria'></span> Algeria",
				"Andorra": "<span class='flag flag-ad' title='Andorra'></span> Andorra",
				"Angola": "<span class='flag flag-ao' title='Angola'></span> Angola",
				"Argentina": "<span class='flag flag-ar' title='Argentina'></span> Argentina",
				"Armenia": "<span class='flag flag-am' title='Armenia'></span> Armenia",
				"Aruba": "<span class='flag flag-aw' title='Aruba'></span> Aruba",
				"Australia": "<span class='flag flag-au' title='Australia'></span> Australia",
				"Austria": "<span class='flag flag-at' title='Austria'></span> Austria",
				"Azerbaijan": "<span class='flag flag-az' title='Azerbaijan'></span> Azerbaijan",
				"Bahamas": "<span class='flag flag-bs' title='Bahamas'></span> Bahamas",
				"Bangladesh": "<span class='flag flag-bd' title='Bangladesh'></span> Bangladesh",
				"Barbados": "<span class='flag flag-bb' title='Barbados'></span> Barbados",
				"Belarus": "<span class='flag flag-by' title='Belarus'></span> Belarus",
				"Belgium": "<span class='flag flag-be' title='Belgium'></span> Belgium",
				"Belize": "<span class='flag flag-bz' title='Belize'></span> Belize",
				"Bermuda": "<span class='flag flag-bm' title='Bermuda'></span> Bermuda",
				"Bhutan": "<span class='flag flag-bt' title='Bhutan'></span> Bhutan",
				"Bolivia": "<span class='flag flag-bo' title='Bolivia'></span> Bolivia",
				"Bosnia and Herzegovina": "<span class='flag flag-ba' title='Bosnia and Herzegovina'></span> Bosnia and Herzegovina",
				"Botswana": "<span class='flag flag-bw' title='Botswana'></span> Botswana",
				"Brazil": "<span class='flag flag-br' title='Brazil'></span> Brazil",
				"Bulgaria": "<span class='flag flag-bg' title='Bulgaria'></span> Bulgaria",
				"Cambodia": "<span class='flag flag-kh' title='Cambodia'></span> Cambodia",
				"Cameroon": "<span class='flag flag-cm' title='Cameroon'></span> Cameroon",
				"Canada": "<span class='flag flag-ca' title='Canada'></span> Canada",
				"Cayman Islands": "<span class='flag flag-ky' title='Cayman Islands'></span> Cayman Islands",
				"Chile": "<span class='flag flag-cl' title='Chile'></span> Chile",
				"China": "<span class='flag flag-cn' title='China'></span> China",
				"Colombia": "<span class='flag flag-co' title='Colombia'></span> Colombia",
				"Costa Rica": "<span class='flag flag-cr' title='Costa Rica'></span> Costa Rica",
				"Croatia": "<span class='flag flag-hr' title='Croatia'></span> Croatia",
				"Cuba": "<span class='flag flag-cu' title='Cuba'></span> Cuba",
				"Curaçao": "<span class='flag flag-cw' title='Curaçao'></span> Curaçao",
				"Cyprus": "<span class='flag flag-cy' title='Cyprus'></span> Cyprus",
				"Czech Republic": "<span class='flag flag-cz' title='Czech Republic'></span> Czech Republic",
				"Denmark": "<span class='flag flag-dk' title='Denmark'></span> Denmark",
				"Djibouti": "<span class='flag flag-dj' title='Djibouti'></span> Djibouti",
				"Dominican Republic": "<span class='flag flag-do' title='Dominican Republic'></span> Dominican Republic",
				"Ecuador": "<span class='flag flag-ec' title='Ecuador'></span> Ecuador",
				"Egypt": "<span class='flag flag-eg' title='Egypt'></span> Egypt",
				"El Salvador": "<span class='flag flag-sv' title='El Salvador'></span> El Salvador",
				"Estonia": "<span class='flag flag-ee' title='Estonia'></span> Estonia",
				"Ethiopia": "<span class='flag flag-et' title='Ethiopia'></span> Ethiopia",
				"Europe": "<span class='flag flag-eu' title='Europe'></span> Europe",
				"Faroe Islands": "<span class='flag flag-fo' title='Faroe Islands'></span> Faroe Islands",
				"Fiji Islands": "<span class='flag flag-fj' title='Fiji Islands'></span> Fiji Islands",
				"Finland": "<span class='flag flag-fi' title='Finland'></span> Finland",
				"France": "<span class='flag flag-fr' title='France'></span> France",
				"Georgia": "<span class='flag flag-ge' title='Georgia'></span> Georgia",
				"Germany": "<span class='flag flag-de' title='Germany'></span> Germany",
				"Greece": "<span class='flag flag-gr' title='Greece'></span> Greece",
				"Guam": "<span class='flag flag-gu' title='Guam'></span> Guam",
				"Guatemala": "<span class='flag flag-gt' title='Guatemala'></span> Guatemala",
				"Guernsey": "<span class='flag flag-gg' title='Guernsey'></span> Guernsey",
				"Honduras": "<span class='flag flag-hn' title='Honduras'></span> Honduras",
				"Hong Kong": "<span class='flag flag-hk' title='Hong Kong'></span> Hong Kong",
				"Hungary": "<span class='flag flag-hu' title='Hungary'></span> Hungary",
				"Iceland": "<span class='flag flag-is' title='Iceland'></span> Iceland",
				"India": "<span class='flag flag-in' title='India'></span> India",
				"Indonesia": "<span class='flag flag-id' title='Indonesia'></span> Indonesia",
				"Iran": "<span class='flag flag-ir' title='Iran'></span> Iran",
				"Iraq": "<span class='flag flag-iq' title='Iraq'></span> Iraq",
				"Ireland": "<span class='flag flag-ie' title='Ireland'></span> Ireland",
				"Isle of Man": "<span class='flag flag-im' title='Isle of Man'></span> Isle of Man",
				"Israel": "<span class='flag flag-il' title='Israel'></span> Israel",
				"Italy": "<span class='flag flag-it' title='Italy'></span> Italy",
				"Jamaica": "<span class='flag flag-jm' title='Jamaica'></span> Jamaica",
				"Japan": "<span class='flag flag-jp' title='Japan'></span> Japan",
				"Jersey": "<span class='flag flag-je' title='Jersey'></span> Jersey",
				"Jordan": "<span class='flag flag-jo' title='Jordan'></span> Jordan",
				"Kazakhstan": "<span class='flag flag-kz' title='Kazakhstan'></span> Kazakhstan",
				"Kenya": "<span class='flag flag-ke' title='Kenya'></span> Kenya",
				"Kuwait": "<span class='flag flag-kw' title='Kuwait'></span> Kuwait",
				"Kyrgyzstan": "<span class='flag flag-kg' title='Kyrgyzstan'></span> Kyrgyzstan",
				"Latvia": "<span class='flag flag-lv' title='Latvia'></span> Latvia",
				"Lebanon": "<span class='flag flag-lb' title='Lebanon'></span> Lebanon",
				"Libya": "<span class='flag flag-ly' title='Libya'></span> Libya",
				"Liechtenstein": "<span class='flag flag-li' title='Liechtenstein'></span> Liechtenstein",
				"Lithuania": "<span class='flag flag-lt' title='Lithuania'></span> Lithuania",
				"Luxembourg": "<span class='flag flag-lu' title='Luxembourg'></span> Luxembourg",
				"Macao": "<span class='flag flag-mo' title='Macao'></span> Macao",
				"Macedonia": "<span class='flag flag-mk' title='Macedonia'></span> Macedonia",
				"Malawi": "<span class='flag flag-mw' title='Malawi'></span> Malawi",
				"Malaysia": "<span class='flag flag-my' title='Malaysia'></span> Malaysia",
				"Malta": "<span class='flag flag-mt' title='Malta'></span> Malta",
				"Mauritania": "<span class='flag flag-mr' title='Mauritania'></span> Mauritania",
				"Mauritius": "<span class='flag flag-mu' title='Mauritius'></span> Mauritius",
				"Mexico": "<span class='flag flag-mx' title='Mexico'></span> Mexico",
				"Moldova": "<span class='flag flag-md' title='Moldova'></span> Moldova",
				"Monaco": "<span class='flag flag-mc' title='Monaco'></span> Monaco",
				"Mongolia": "<span class='flag flag-mn' title='Mongolia'></span> Mongolia",
				"Montenegro": "<span class='flag flag-me' title='Montenegro'></span> Montenegro",
				"Morocco": "<span class='flag flag-ma' title='Morocco'></span> Morocco",
				"Mozambique": "<span class='flag flag-mz' title='Mozambique'></span> Mozambique",
				"Myanmar": "<span class='flag flag-mm' title='Myanmar'></span> Myanmar",
				"Nepal": "<span class='flag flag-np' title='Nepal'></span> Nepal",
				"Netherlands": "<span class='flag flag-nl' title='Netherlands'></span> Netherlands",
				"New Caledonia": "<span class='flag flag-nc' title='New Caledonia'></span> New Caledonia",
				"New Zealand": "<span class='flag flag-nz' title='New Zealand'></span> New Zealand",
				"Nigeria": "<span class='flag flag-ng' title='Nigeria'></span> Nigeria",
				"Norway": "<span class='flag flag-no' title='Norway'></span> Norway",
				"Pakistan": "<span class='flag flag-pk' title='Pakistan'></span> Pakistan",
				"Palestine": "<span class='flag flag-ps' title='Palestine'></span> Palestine",
				"Panama": "<span class='flag flag-pa' title='Panama'></span> Panama",
				"Paraguay": "<span class='flag flag-py' title='Paraguay'></span> Paraguay",
				"Peru": "<span class='flag flag-pe' title='Peru'></span> Peru",
				"Philippines": "<span class='flag flag-ph' title='Philippines'></span> Philippines",
				"Poland": "<span class='flag flag-pl' title='Poland'></span> Poland",
				"Portugal": "<span class='flag flag-pt' title='Portugal'></span> Portugal",
				"Puerto Rico": "<span class='flag flag-pr' title='Puerto Rico'></span> Puerto Rico",
				"Qatar": "<span class='flag flag-qa' title='Qatar'></span> Qatar",
				"Romania": "<span class='flag flag-ro' title='Romania'></span> Romania",
				"Russian Federation": "<span class='flag flag-ru' title='Russian Federation'></span> Russian Federation",
				"Réunion": "<span class='flag flag-re' title='Réunion'></span> Réunion",
				"Saint Vincent and the Grenadines": "<span class='flag flag-vc' title='Saint Vincent and the Grenadines'></span> Saint Vincent and the Grenadines",
				"Saudi Arabia": "<span class='flag flag-sa' title='Saudi Arabia'></span> Saudi Arabia",
				"Serbia": "<span class='flag flag-rs' title='Serbia'></span> Serbia",
				"Seychelles": "<span class='flag flag-sc' title='Seychelles'></span> Seychelles",
				"Singapore": "<span class='flag flag-sg' title='Singapore'></span> Singapore",
				"Slovakia": "<span class='flag flag-sk' title='Slovakia'></span> Slovakia",
				"Slovenia": "<span class='flag flag-si' title='Slovenia'></span> Slovenia",
				"South Africa": "<span class='flag flag-za' title='South Africa'></span> South Africa",
				"South Korea": "<span class='flag flag-kr' title='South Korea'></span> South Korea",
				"Spain": "<span class='flag flag-es' title='Spain'></span> Spain",
				"Sri Lanka": "<span class='flag flag-lk' title='Sri Lanka'></span> Sri Lanka",
				"Sweden": "<span class='flag flag-se' title='Sweden'></span> Sweden",
				"Switzerland": "<span class='flag flag-ch' title='Switzerland'></span> Switzerland",
				"Taiwan": "<span class='flag flag-tw' title='Taiwan'></span> Taiwan",
				"Tanzania": "<span class='flag flag-tz' title='Tanzani'></span> Tanzania",
				"Thailand": "<span class='flag flag-th' title='Thailand'></span> Thailand",
				"Trinidad and Tobago": "<span class='flag flag-tt' title='Trinidad and Tobago'></span> Trinidad and Tobago",
				"Tunisia": "<span class='flag flag-tn' title='Tunisia'></span> Tunisia",
				"Turkey": "<span class='flag flag-tr' title='Turkey'></span> Turkey",
				"U.S. Virgin Islands": "<span class='flag flag-vi' title='U.S. Virgin Islands'></span> U.S. Virgin Islands",
				"Uganda": "<span class='flag flag-ug' title='Uganda'></span> Uganda",
				"Ukraine": "<span class='flag flag-ua' title='Ukraine'></span> Ukraine",
				"United Arab Emirates": "<span class='flag flag-ae' title='United Arab Emirates'></span> United Arab Emirates",
				"United Kingdom": "<span class='flag flag-gb' title='United Kingdom'></span> United Kingdom",
				"United States": "<span class='flag flag-us' title='United States'></span> United States",
				"Unknown": "<span class='flag flag-xx' title='Unknown'></span> Unknown",
				"Uruguay": "<span class='flag flag-uy' title='Uruguay'></span> Uruguay",
				"Venezuela": "<span class='flag flag-ve' title='Venezuela'></span> Venezuela",
				"Vietnam": "<span class='flag flag-vn' title='Vietnam'></span> Vietnam",
				"Anarchist": "<span class='trollflag trollflag-an' title='Anarchist'></span> Anarchist",
				"Anarcho-Capitalist": "<span class='trollflag trollflag-ac' title='Anarcho-Capitalist'></span> Anarcho-Capitalist",
				"Black Nationalist|Black Lives Matter": "<span class='trollflag trollflag-bl' title='Black Nationalist'></span> Black Nationalist / Black Lives Matter",
				"Catalonia": "<span class='trollflag trollflag-ct' title='Catalonia'></span> Catalonia",
				"Commie|Communist": "<span class='trollflag trollflag-cm' title='Commie'></span> Commie / Communist",
				"Confederate": "<span class='trollflag trollflag-cf' title='Confederate'></span> Confederate",
				"Democrat": "<span class='trollflag trollflag-dm' title='Democrat'></span> Democrat",
				"Templar|DEUS VULT": "Templar / DEUS VULT",
				"Europe|European": "<span class='trollflag trollflag-eu' title='European'></span> Europe / European",
				"Fascist": "<span class='trollflag trollflag-fc' title='Fascist'></span> Fascist",
				"Gadsden": "<span class='trollflag trollflag-gn' title='Gadsden'></span> Gadsden",
				"Gay|LGBT": "<span class='trollflag trollflag-gy' title='Gay'></span> Gay / LGBT",
				"Hippie": "<span class='trollflag trollflag-pc' title='Hippie'></span> Hippie",
				"Jihadi": "<span class='trollflag trollflag-jh' title='Jihadi'></span> Jihadi",
				"Kekistani": "<span class='trollflag trollflag-kn' title='Kekistani'></span> Kekistani",
				"Muslim": "<span class='trollflag trollflag-mf' title='Muslim'></span> Muslim",
				"National Bolshevik": "<span class='trollflag trollflag-nb' title='National Bolshevik'></span> National Bolshevik",
				"Nazi": "<span class='trollflag trollflag-nz' title='Nazi'></span> Nazi",
				"North Korea": "North Korea",
				"Obama": "Obama",
				"Pirate": "<span class='trollflag trollflag-pr' title='Pirate'></span> Pirate",
				"Rebel": "Rebel",
				"Republican": "<span class='trollflag trollflag-re' title='Republican'></span> Republican",
				"Templar": "<span class='trollflag trollflag-tm' title='Templar'></span> Templar",
				"Texan": "Texan",
				"Tree Hugger": "<span class='trollflag trollflag-tr' title='Tree Hugger'></span> Tree Hugger",
				"United Nations": "<span class='trollflag trollflag-un' title='United Nations'></span> United Nations",
				"White Supremacist": "<span class='trollflag trollflag-wp' title='White Supremacist'></span> White Supremacist",
				},
			"default": ""
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
				"posts-only": "All matching posts",
				"full-threads": "All posts in threads with matching posts (full threads)",
				"dense-threads": "All posts in threads in which at least x% of posts match (dense threads)",
				"match-ids": "Only posts matching the given post IDs"
			},
			"default": "posts-only"
		},
		"scope_density": {
			"type": UserInput.OPTION_TEXT,
			"help": "Min. density %",
			"min": 0,
			"max": 100,
			"default": 15,
			"tooltip": "At least this many % of posts in the thread must match the query"
		},
		"scope_length": {
			"type": UserInput.OPTION_TEXT,
			"help": "Min. dense thread length",
			"min": 30,
			"default": 30,
			"tooltip": "A thread must at least be this many posts long to qualify as a 'dense thread'"
		},
		"valid_ids": {
			"type": UserInput.OPTION_TEXT,
			"help": "Post IDs (comma-separated)"
		}
	}

	def get_items_simple(self, query):
		"""
		Fast-lane for simpler queries that don't need the intermediate step
		where Sphinx is queried

		In practice this means queries that only select by time period,
		country code and/or random sample
		:param query:
		:return:
		"""
		where = []
		replacements = [query.get("board", "")]

		if query.get("min_date", 0):
			try:
				where.append("p.timestamp >= %s")
				replacements.append(int(query.get("min_date")))
			except ValueError:
				pass

		if query.get("max_date", 0):
			try:
				replacements.append(int(query.get("max_date")))
				where.append("p.timestamp < %s")
			except ValueError:
				pass

		if query.get("country_name", None):

			# Separate merged names
			country_names = []
			for country_name in query["country_names"]:
				country_name = country_name.split("|")
				for c in country_name:
					country_names.append(c)

			where.append("p.country_name IN (%s)")

			replacements.append(country_names)

		sql_query = ("SELECT p.*, t.board " \
					 "FROM posts_" + self.prefix + " AS p " \
					 "LEFT JOIN threads_" + self.prefix + " AS t " \
					 "ON t.id = p.thread_id " \
					 "WHERE t.board = %s ")

		if where:
			sql_query += " AND " + " AND ".join(where)

		if query.get("search_scope", None) == "match-ids":
			try:
				query_ids = query.get("valid_ids", None)

				# Parse query IDs
				if query_ids:
					query_ids = query_ids.split(",")
					valid_query_ids = []
					for query_id in query_ids:
						try:
							# Make sure the text can be parsed to an integer.
							query_id = int(query_id.strip())
							valid_query_ids.append(str(query_id))
						except ValueError:
							# If not, just skip it.
							continue
					if not valid_query_ids:
						self.dataset.update_status("The IDs inserted are not valid 4chan post IDs.")
						return None

					if len(valid_query_ids) > 5000000:
						self.dataset.update_status("Too many IDs inserted. Max 5.000.000.")
						return None

					valid_query_ids = "(" + ",".join(valid_query_ids) + ")"
					sql_query = "SELECT * FROM (" + sql_query + "AND p.id IN " + valid_query_ids + ") AS full_table ORDER BY full_table.timestamp ASC"

				else:
					self.dataset.update_status("No 4chan post IDs inserted.")
					return None

			except ValueError:
				pass

		else:
			sql_query += " ORDER BY p.timestamp ASC"

		return self.db.fetchall_interruptable(self.queue, sql_query, replacements)

	def get_items_complex(self, query):
		"""
		Complex queries that require full-text search capabilities

		This adds an intermediate step where Sphinx is queried to get IDs for
		matching posts, which are then handled further.

		As much as possible is pre-selected through Sphinx, and then the rest
		is handled through PostgreSQL queries.

		:param dict query:  Query parameters, as part of the DataSet object
		:return list:  Posts, sorted by thread and post ID, in ascending order
		"""

		# first, build the sphinx query
		where = []
		replacements = []
		match = []

		if query.get("min_date", None):
			try:
				if int(query.get("min_date")) > 0:
					where.append("timestamp >= %s")
					replacements.append(int(query.get("min_date")))
			except ValueError:
				pass

		if query.get("max_date", None):
			try:
				if int(query.get("max_date")) > 0:
					replacements.append(int(query.get("max_date")))
					where.append("timestamp < %s")
			except ValueError:
				pass

		if query.get("board", None) and query["board"] != "*":
			where.append("board = %s")
			replacements.append(query["board"])

		# escape full text matches and convert quotes
		if query.get("body_match", None):
			match.append("@body " + self.convert_for_sphinx(query["body_match"]))

		if query.get("subject_match", None):
			match.append("@subject " + self.convert_for_sphinx(query["subject_match"]))

		# handle country names through sphinx
		if query.get("country_name", None) and not query.get("check_dense_country", None):
			if query.get("country_name", "") == "eu":
				where.append("country_name IN %s")
				replacements.append(self.eu_countries)
			else:
				where.append("country_name IN %s")
				replacements.append(query.get("country_name"))

		# both possible FTS parameters go in one MATCH() operation
		if match:
			where.append("MATCH(%s)")
			replacements.append(" ".join(match))

		# query Sphinx
		self.dataset.update_status("Searching for matches")
		where = " AND ".join(where)
		posts = self.fetch_sphinx(where, replacements)

		if posts is None:
			return posts
		elif len(posts) == 0:
			# no results
			self.dataset.update_status("Query finished, but no results were found.")
			return None

		# query posts database
		self.dataset.update_status("Found %i matches. Collecting post data" % len(posts))
		datafetch_start = time.time()
		self.log.info("Collecting post data from database")
		columns = ", ".join(self.return_cols)

		postgres_where = []
		postgres_replacements = []

		# postgres_where.append("board = %s")
		# postgres_replacements.append(query.get("board"))

		posts_full = self.fetch_posts(tuple([post["post_id"] for post in posts]), postgres_where, postgres_replacements)

		self.dataset.update_status("Post data collected")
		self.log.info("Full posts query finished in %i seconds." % (time.time() - datafetch_start))

		return posts_full

	def convert_for_sphinx(self, string):
		"""
		SphinxQL has a couple of special characters that should be escaped if
		they are part of a query, but no native function is available to
		provide this functionality. This method provides it.

		Thanks: https://stackoverflow.com/a/6288301

		Also converts curly quotes to straight quotes to catch users copy-pasting
		their search full match queries from e.g. word.

		:param str string:  String to escape
		:return str: Escaped string
		"""

		# Convert curly quotes
		string = string.replace("“", "\"").replace("”", "\"")
		# Escape forward slashes
		string = string.replace("/", "\\/")
		# Escape @
		string = string.replace("@", "\\@")
		return string

	def fetch_posts(self, post_ids, where=None, replacements=None):
		"""
		Fetch post data from database

		:param list post_ids:  List of post IDs to return data for
		:return list: List of posts, with a dictionary representing the database record for each post
		"""
		if not where:
			where = []

		if not replacements:
			replacements = []

		columns = ", ".join(self.return_cols)
		where.append("id IN %s")
		replacements.append(post_ids)

		if self.interrupted:
			raise ProcessorInterruptedException("Interrupted while fetching post data")

		query = "SELECT " + columns + " FROM posts_" + self.prefix + " WHERE " + " AND ".join(
			where) + " ORDER BY id ASC"
		return self.db.fetchall_interruptable(self.queue, query, replacements)

	def fetch_threads(self, thread_ids):
		"""
		Fetch post from database for given threads

		:param list thread_ids: List of thread IDs to return post data for
		:return list: List of posts, with a dictionary representing the database record for each post
		"""
		columns = ", ".join(self.return_cols)

		if self.interrupted:
			raise ProcessorInterruptedException("Interrupted while fetching thread data")

		return self.db.fetchall_interruptable(self.queue,
			"SELECT " + columns + " FROM posts_" + self.prefix + " WHERE thread_id IN %s ORDER BY thread_id ASC, id ASC",
											  (thread_ids,))

	def fetch_sphinx(self, where, replacements):
		"""
		Query Sphinx for matching post IDs

		:param str where:  Drop-in WHERE clause (without the WHERE keyword) for the Sphinx query
		:param list replacements:  Values to use for parameters in the WHERE clause that should be parsed
		:return list:  List of matching posts; each post as a dictionary with `thread_id` and `post_id` as keys
		"""

		# if a Sphinx query is interrupted, pymysql will not actually raise an
		# exception but just a warning. But we need to detect interruption, so here we
		# make sure pymysql warnings are converted to exceptions
		warnings.filterwarnings("error", module=".*pymysql.*")

		sphinx_start = time.time()
		sphinx = self.get_sphinx_handler()

		results = []
		try:
			sql = "SELECT thread_id, post_id FROM `" + self.prefix + "_posts` WHERE " + where + " LIMIT 5000000 OPTION max_matches = 5000000, ranker = none, boolean_simplify = 1, sort_method = kbuffer, cutoff = 5000000"
			parsed_query = sphinx.mogrify(sql, replacements)
			self.log.info("Running Sphinx query %s " % parsed_query)
			self.running_query = parsed_query
			results = sphinx.fetchall(parsed_query, [])
			sphinx.close()
		except SphinxWarning as e:
			# this is a pymysql warning converted to an exception
			if "query was killed" in str(e):
				self.dataset.update_status("Search was interruped and will restart later")
				raise ProcessorInterruptedException("Interrupted while running Sphinx query")
			else:
				self.dataset.update_status("Error while querying full-text search index", is_final=True)
				self.log.error("Sphinx warning: %s" % e)
		except OperationalError as e:
			self.dataset.update_status(
				"Your query timed out. This is likely because it matches too many posts. Try again with a narrower date range or a more specific search query.",
				is_final=True)
			self.log.info("Sphinx query timed out after %i seconds" % (time.time() - sphinx_start))
			return None
		except ProgrammingError as e:
			if "invalid packet size" in str(e) or "query timed out" in str(e):
				self.dataset.update_status(
					"Error during query. Your query matches too many items. Try again with a narrower date range or a more specific search query.",
					is_final=True)
			elif "syntax error" in str(e):
				self.dataset.update_status(
					"Error during query. Your query syntax may be invalid (check for loose parentheses).",
					is_final=True)
			else:
				self.dataset.update_status(
					"Error during query. Please try a narrow query and double-check your syntax.", is_final=True)
				self.log.error("Sphinx crash during query %s: %s" % (self.dataset.key, e))
			return None


		self.log.info("Sphinx query finished in %i seconds, %i results." % (time.time() - sphinx_start, len(results)))
		return results

	def get_sphinx_handler(self):
		"""
		Get a MySQL database object that can be used to interact with Sphinx

		:return MySQLDatabase:
		"""
		return MySQLDatabase(
			host="localhost",
			user=config.DB_USER,
			password=config.DB_PASSWORD,
			port=9306,
			logger=self.log
		)

	def get_thread_sizes(self, thread_ids, min_length):
		"""
		Get thread lengths for all threads

		:param tuple thread_ids:  List of thread IDs to fetch lengths for
		:param int min_length:  Min length for a thread to be included in the
		results
		:return dict:  Threads sizes, with thread IDs as keys
		"""
		# find total thread lengths for all threads in initial data set
		thread_sizes = {row["thread_id"]: row["num_posts"] for row in self.db.fetchall_interruptable(
			self.queue, "SELECT COUNT(*) as num_posts, thread_id FROM posts_" + self.prefix + " WHERE thread_id IN %s GROUP BY thread_id",
			(thread_ids,)) if int(row["num_posts"]) > min_length}

		return thread_sizes

	def validate_query(query, request, user):
		"""
		Validate input for a dataset query on the 4chan data source.

		Will raise a QueryParametersException if invalid parameters are
		encountered. Mutually exclusive parameters may also be sanitised by
		ignoring either of the mutually exclusive options.

		:param dict query:  Query parameters, from client-side.
		:param request:  Flask request
		:param User user:  User object of user who has submitted the query
		:return dict:  Safe query parameters
		"""

		# this is the bare minimum, else we can't narrow down the full data set
		if not user.is_admin() and not user.get_value("4chan.can_query_without_keyword", False) and not query.get("body_match", None) and not query.get("subject_match", None) and query.get("search_scope",	"") != "random-sample":
			raise QueryParametersException("Please provide a message or subject search query")

		query["min_date"], query["max_date"] = query["daterange"]

		del query["daterange"]
		if query.get("search_scope") not in ("dense-threads",):
			del query["scope_density"]
			del query["scope_length"]

		if query.get("search_scope") not in ("match-ids",) and "valid_ids" in query.keys():
			del query["valid_ids"]

		return query

	def request_interrupt(self, level=1):
		"""
		Request an abort of this worker

		This is implemented in the basic worker class, and that method is
		called, but this additionally kills any running Sphinx queries because
		they are blocking, and will prevent the worker from actually stopping
		unless killed.

		:param int level:  Retry or cancel? Either `self.INTERRUPT_RETRY` or
		`self.INTERRUPT_CANCEL`.
		"""
		super(Search4Chan, self).request_interrupt(level)

		sphinx = self.get_sphinx_handler()
		threads = sphinx.fetchall("SHOW THREADS OPTION columns=5000")
		for thread in threads:
			if thread["Info"] == self.running_query:
				self.log.info("Killing Sphinx query %s" % thread["Tid"])
				sphinx.query("KILL %s" % thread["Tid"])
