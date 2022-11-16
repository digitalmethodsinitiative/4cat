"""
4chan Search via Sphinx
"""
import warnings
import time

from pymysql import OperationalError, ProgrammingError
from pymysql.err import Warning as SphinxWarning

import common.config_manager as config
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
	is_local = True	# Whether this datasource is locally scraped
	is_static = False	# Whether this datasource is still updated

	# Columns to return in csv
	return_cols = ['thread_id', 'id', 'timestamp', 'board', 'body', 'subject', 'author', 'image_file', 'image_md5',
				   'country_name', 'country_code', 'timestamp_deleted']

	references = [
		"[4chan API](https://github.com/4chan/4chan-API)",
		"[4plebs](https://archive.4plebs.org)"
	]
	
	# before running a sphinx query, store it here so it can be cancelled via
	# request_abort() later
	running_query = ""

	options = {
		"intro": {
			"type": UserInput.OPTION_INFO,
			"help": "Results are limited to 5 million items maximum. Be sure to read the [query "
					"syntax](/data-overview/4chan#query-syntax) for local data sources first - your query design will "
					"significantly impact the results. Note that large queries can take a long time to complete!"
		},
		"board": {
			"type": UserInput.OPTION_CHOICE,
			"options": {b: b for b in config.get('DATASOURCES').get(prefix, {}).get("boards", [])},
			"help": "Board",
			"default": config.get('DATASOURCES').get(prefix, {}).get("boards", [""])[0]
		},
		"body_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Post contains"
		},
		"subject_match": {
			"type": UserInput.OPTION_TEXT,
			"help": "Subject contains"
		},
		"deleted_posts": {
			"type": UserInput.OPTION_INFO,
			"help": "Posts deleted by moderators may be excluded. <strong>Note:</strong> replies to deleted OPs are seen as not deleted."
		},
		"get_deleted": {
			"type": UserInput.OPTION_TOGGLE,
			"default": False,
			"help": "Include deleted posts"
		},
		"country_name": {
			"type": UserInput.OPTION_MULTI_SELECT,
			"help": "Poster country",
			"board_specific": ["pol", "sp", "int"],
			"tooltip": "The IP-derived flag attached to posts. Can be an actual country or \"meme flag\". Leave empty for all.",
			"options": {
				"Armenia|Albania|Andorra|Austria|Belarus|Belgium|Bosnia and Herzegovina|Bulgaria|Croatia|Cyprus|Czech Republic|Denmark|Estonia|Finland|France|Germany|Greece|Hungary|Iceland|Republic of Ireland|Italy|Kosovo|Latvia|Liechtenstein|Lithuania|Luxembourg|Republic of Macedonia|North Macedonia|Macedonia|Malta|Moldova|Monaco|Montenegro|Netherlands|The Netherlands|Norway|Poland|Portugal|Romania|Russia|San Marino|Serbia|Slovakia|Slovenia|Spain|Sweden|Switzerland|Turkey|Ukraine|United Kingdom|Vatican City": "European countries",
				"Afghanistan": "<span class='flag flag-AF' title='Afghanistan'></span> Afghanistan",
				"Aland Islands|Aland": "<span class='flag flag-AX' title='Aland / Aland Islands'></span> Aland Islands",
				"Albania": "<span class='flag flag-AL' title='Albania'></span> Albania",
				"Algeria": "<span class='flag flag-DZ' title='Algeria'></span> Algeria",
				"American Samoa": "<span class='flag flag-AS title='American Samoa's'></span> American Samoa",
				"Andorra": "<span class='flag flag-AD' title='Andorra'></span> Andorra",
				"Angola": "<span class='flag flag-AO' title='Angola'></span> Angola",
				"Anguilla": "<span class='flag flag-AI' title='Anguilla'></span> Anguilla",
				"Antarctica": "<span class='flag flag-AQ' title='Antarctica'></span> Antarctica",
				"Antigua and Barbuda": "<span class='flag flag-AG' title='Antigua and Barbuda'></span> Antigua and Barbuda",
				"Argentina": "<span class='flag flag-AR' title='Argentina'></span> Argentina",
				"Armenia": "<span class='flag flag-AM' title='Armenia'></span> Armenia",
				"Aruba": "<span class='flag flag-AW' title='Aruba'></span> Aruba",
				"Asia/Pacific Region": "<span class='flag flag-AP' title='Asia/Pacific Region'></span> Asia/Pacific Region",
				"Australia": "<span class='flag flag-AU' title='Australia'></span> Australia",
				"Austria": "<span class='flag flag-AT' title='Austria'></span> Austria",
				"Azerbaijan": "<span class='flag flag-AZ' title='Azerbaijan'></span> Azerbaijan",
				"Bahamas": "<span class='flag flag-BS' title='Bahamas'></span> Bahamas",
				"Bahrain": "<span class='flag flag-BH' title='Bahrain'></span> Bahrain",
				"Bangladesh": "<span class='flag flag-BD' title='Bangladesh'></span> Bangladesh",
				"Barbados": "<span class='flag flag-BB' title='Barbados'></span> Barbados",
				"Belarus": "<span class='flag flag-BY' title='Belarus'></span> Belarus",
				"Belgium": "<span class='flag flag-BE' title='Belgium'></span> Belgium",
				"Belize": "<span class='flag flag-BZ' title='Belize'></span> Belize",
				"Benin": "<span class='flag flag-BJ' title='Benin'></span> Benin",
				"Bermuda": "<span class='flag flag-BM' title='Bermuda'></span> Bermuda",
				"Bhutan": "<span class='flag flag-BT' title='Bhutan'></span> Bhutan",
				"Bolivia": "<span class='flag flag-BO' title='Bolivia'></span> Bolivia",
				"Bonaire, Sint Eustatius and Saba": "<span class='flag flag-BQ' title='Bonaire, Sint Eustatius and Saba'></span> Bonaire, Sint Eustatius and Saba",
				"Bosnia and Herzegovina": "<span class='flag flag-BA' title='Bosnia and Herzegovina'></span> Bosnia and Herzegovina",
				"Botswana": "<span class='flag flag-BW' title='Botswana'></span> Botswana",
				"Bouvet Island": "<span class='flag flag-BV' title='Bouvet Island'></span> Bouvet Island",
				"Brazil": "<span class='flag flag-BR' title='Brazil'></span> Brazil",
				"British Indian Ocean Territory": "<span class='flag flag-IO' title='British Indian Ocean Territory'></span> British Indian Ocean Territory",
				"British Virgin Islands": "<span class='flag flag-VG' title='British Virgin Islands'></span> British Virgin Islands",
				"Brunei": "<span class='flag flag-BN' title='Brunei'></span> Brunei",
				"Bulgaria": "<span class='flag flag-BG' title='Bulgaria'></span> Bulgaria",
				"Burkina Faso": "<span class='flag flag-BF' title='Burkina Faso'></span> Burkina Faso",
				"Burundi": "<span class='flag flag-BI' title='Burundi'></span> Burundi",
				"Cambodia": "<span class='flag flag-KH' title='Cambodia'></span> Cambodia",
				"Cameroon": "<span class='flag flag-CM' title='Cameroon'></span> Cameroon",
				"Canada": "<span class='flag flag-CA' title='Canada'></span> Canada",
				"Cape Verde": "<span class='flag flag-CV' title='Cape Verde'></span> Cape Verde",
				"Cayman Islands": "<span class='flag flag-KY' title='Cayman Islands'></span> Cayman Islands",
				"Central African Republic": "<span class='flag flag-CF' title='Central African Republic'></span> Central African Republic",
				"Chad": "<span class='flag flag-TD' title='Chad'></span> Chad",
				"Chile": "<span class='flag flag-CL' title='Chile'></span> Chile",
				"China": "<span class='flag flag-CN' title='China'></span> China",
				"Christmas Island": "<span class='flag flag-CX' title='Christmas Island'></span> Christmas Island",
				"Cocos (Keeling) Islands": "<span class='flag flag-CC' title='Cocos (Keeling) Islands'></span> Cocos (Keeling) Islands",
				"Colombia": "<span class='flag flag-CO' title='Colombia'></span> Colombia",
				"Comoros": "<span class='flag flag-KM' title='Comoros'></span> Comoros",
				"Congo|Democratic Republic of the Congo": "<span class='flag flag-CD' title='Congo'></span> Congo",
				"Cook Islands": "<span class='flag flag-CK' title='Cook Islands'></span> Cook Islands",
				"Costa Rica": "<span class='flag flag-CR' title='Costa Rica'></span> Costa Rica",
				"Croatia": "<span class='flag flag-HR' title='Croatia'></span> Croatia",
				"Cuba": "<span class='flag flag-CU' title='Cuba'></span> Cuba",
				"Curaçao|Curacao": "<span class='flag flag-CW' title='Curaçao'></span> Curaçao",
				"Cyprus": "<span class='flag flag-CY' title='Cyprus'></span> Cyprus",
				"Czech Republic": "<span class='flag flag-CZ' title='Czech Republic'></span> Czech Republic",
				"Côte d'Ivoire|Ivory Coast": "<span class='flag flag-CI' title='Côte d'Ivoire'></span> Côte d'Ivoire",
				"Denmark": "<span class='flag flag-DK' title='Denmark'></span> Denmark",
				"Djibouti": "<span class='flag flag-DJ' title='Djibouti'></span> Djibouti",
				"Dominica": "<span class='flag flag-DM' title='Dominica'></span> Dominica",
				"Dominican Republic": "<span class='flag flag-DO' title='Dominican Republic'></span> Dominican Republic",
				"Ecuador": "<span class='flag flag-EC' title='Ecuador'></span> Ecuador",
				"Egypt": "<span class='flag flag-EG' title='Egypt'></span> Egypt",
				"El Salvador": "<span class='flag flag-SV' title='El Salvador'></span> El Salvador",
				"Equatorial Guinea": "<span class='flag flag-GQ' title='Equatorial Guinea'></span> Equatorial Guinea",
				"Eritrea": "<span class='flag flag-ER' title='Eritrea'></span> Eritrea",
				"Estonia": "<span class='flag flag-EE' title='Estonia'></span> Estonia",
				"Ethiopia": "<span class='flag flag-ET' title='Ethiopia'></span> Ethiopia",
				"Falkland Islands|Falkland Islands (Malvinas)": "<span class='flag flag-FK' title='Falkland Islands'></span> Falkland Islands",
				"Faroe Islands": "<span class='flag flag-FO' title='Faroe Islands'></span> Faroe Islands",
				"Fiji Islands": "<span class='flag flag-FJ' title='Fiji Islands'></span> Fiji Islands",
				"Finland": "<span class='flag flag-FI' title='Finland'></span> Finland",
				"France": "<span class='flag flag-FR' title='France'></span> France",
				"French Guiana": "<span class='flag flag-GF' title='French Guiana'></span> French Guiana",
				"French Polynesia": "<span class='flag flag-PF' title='French Polynesia'></span> French Polynesia",
				"Gabon": "<span class='flag flag-GA' title='Gabon'></span> Gabon",
				"Gambia": "<span class='flag flag-GM' title='Gambia'></span> Gambia",
				"Georgia": "<span class='flag flag-GE' title='Georgia'></span> Georgia",
				"Germany": "<span class='flag flag-DE' title='Germany'></span> Germany",
				"Ghana": "<span class='flag flag-GH' title='Ghana'></span> Ghana",
				"Gibraltar": "<span class='flag flag-GI' title='Gibraltar'></span> Gibraltar",
				"Greece": "<span class='flag flag-GR' title='Greece'></span> Greece",
				"Greenland": "<span class='flag flag-GL' title='Greenland'></span> Greenland",
				"Grenada": "<span class='flag flag-GD' title='Grenada'></span> Grenada",
				"Guadeloupe": "<span class='flag flag-GP' title='Guadeloupe'></span> Guadeloupe",
				"Guam": "<span class='flag flag-GU' title='Guam'></span> Guam",
				"Guatemala": "<span class='flag flag-GT' title='Guatemala'></span> Guatemala",
				"Guernsey": "<span class='flag flag-GG' title='Guernsey'></span> Guernsey",
				"Guinea-Bissau": "<span class='flag flag-GW' title='Guinea-Bissau'></span> Guinea-Bissau",
				"Guinea|French Guinea": "<span class='flag flag-GN' title='Guinea'></span> Guinea / French Guinea",
				"Guyana|Guiana": "<span class='flag flag-GY' title='Guyana'></span> Guyana",
				"Haiti": "<span class='flag flag-HT' title='Haiti'></span> Haiti",
				"Heard Island and McDonald Islands": "<span class='flag flag-HM' title='Heard Island and McDonald Islands'></span> Heard Island and McDonald Islands",
				"Holy See (Vatican City State)": "<span class='flag flag-VA' title='Holy See (Vatican City State)'></span> Holy See (Vatican City State)",
				"Honduras": "<span class='flag flag-HN' title='Honduras'></span> Honduras",
				"Hong Kong": "<span class='flag flag-HK' title='Hong Kong'></span> Hong Kong",
				"Hungary": "<span class='flag flag-HU' title='Hungary'></span> Hungary",
				"Iceland": "<span class='flag flag-IS' title='Iceland'></span> Iceland",
				"India": "<span class='flag flag-IN' title='India'></span> India",
				"Indonesia": "<span class='flag flag-ID' title='Indonesia'></span> Indonesia",
				"Iran": "<span class='flag flag-IR' title='Iran'></span> Iran",
				"Iraq": "<span class='flag flag-IQ' title='Iraq'></span> Iraq",
				"Ireland": "<span class='flag flag-IE' title='Ireland'></span> Ireland",
				"Isle of Man": "<span class='flag flag-IM' title='Isle of Man'></span> Isle of Man",
				"Israel": "<span class='flag flag-IL' title='Israel'></span> Israel",
				"Italy": "<span class='flag flag-IT' title='Italy'></span> Italy",
				"Jamaica": "<span class='flag flag-JM' title='Jamaica'></span> Jamaica",
				"Japan": "<span class='flag flag-JP' title='Japan'></span> Japan",
				"Jersey": "<span class='flag flag-JE' title='Jersey'></span> Jersey",
				"Jordan": "<span class='flag flag-JO' title='Jordan'></span> Jordan",
				"Kazakhstan": "<span class='flag flag-KZ' title='Kazakhstan'></span> Kazakhstan",
				"Kenya": "<span class='flag flag-KE' title='Kenya'></span> Kenya",
				"Kiribati": "<span class='flag flag-KI' title='Kiribati'></span> Kiribati",
				"Kosovo": "<span class='flag flag-XK' title='Kosovo'></span> Kosovo",
				"Kuwait": "<span class='flag flag-KW' title='Kuwait'></span> Kuwait",
				"Kyrgyzstan": "<span class='flag flag-KG' title='Kyrgyzstan'></span> Kyrgyzstan",
				"Laos|Lao People's Democratic Republic": "<span class='flag flag-LA' title='Laos'></span> Laos",
				"Latvia": "<span class='flag flag-LV' title='Latvia'></span> Latvia",
				"Lebanon": "<span class='flag flag-LB' title='Lebanon'></span> Lebanon",
				"Lesotho": "<span class='flag flag-LS' title='Lesotho'></span> Lesotho",
				"Liberia": "<span class='flag flag-LR' title='Liberia'></span> Liberia",
				"Libya": "<span class='flag flag-LY' title='Libya'></span> Libya",
				"Liechtenstein": "<span class='flag flag-LI' title='Liechtenstein'></span> Liechtenstein",
				"Lithuania": "<span class='flag flag-LT' title='Lithuania'></span> Lithuania",
				"Luxembourg": "<span class='flag flag-LU' title='Luxembourg'></span> Luxembourg",
				"Macau|Macao": "<span class='flag flag-MO' title='Macao'></span> Macao",
				"Macedonia": "<span class='flag flag-MK' title='Macedonia'></span> Macedonia",
				"Madagascar": "<span class='flag flag-MG' title='Madagascar'></span> Madagascar",
				"Malawi": "<span class='flag flag-MW' title='Malawi'></span> Malawi",
				"Malaysia": "<span class='flag flag-MY' title='Malaysia'></span> Malaysia",
				"Maldives": "<span class='flag flag-MV' title='Maldives'></span> Maldives",
				"Mali": "<span class='flag flag-ML' title='Mali'></span> Mali",
				"Malta": "<span class='flag flag-MT' title='Malta'></span> Malta",
				"Marshall Islands": "<span class='flag flag-MH' title='Marshall Islands'></span> Marshall Islands",
				"Martinique": "<span class='flag flag-MQ' title='Martinique'></span> Martinique",
				"Mauritania": "<span class='flag flag-MR' title='Mauritania'></span> Mauritania",
				"Mauritius": "<span class='flag flag-MU' title='Mauritius'></span> Mauritius",
				"Mayotte": "<span class='flag flag-YT' title='Mayotte'></span> Mayotte",
				"Mexico": "<span class='flag flag-MX' title='Mexico'></span> Mexico",
				"Micronesia|Federated States of Micronesia": "<span class='flag flag-FM' title='Federated States of Micronesia'></span> Federated States of Micronesia",
				"Moldova|Moldova, Republic of": "<span class='flag flag-MD' title='Moldova'></span> Moldova",
				"Monaco": "<span class='flag flag-MC' title='Monaco'></span> Monaco",
				"Mongolia": "<span class='flag flag-MN' title='Mongolia'></span> Mongolia",
				"Montenegro": "<span class='flag flag-ME' title='Montenegro'></span> Montenegro",
				"Montserrat": "<span class='flag flag-MS' title='Montserrat'></span> Montserrat",
				"Morocco": "<span class='flag flag-MA' title='Morocco'></span> Morocco",
				"Mozambique": "<span class='flag flag-MZ' title='Mozambique'></span> Mozambique",
				"Myanmar": "<span class='flag flag-MM' title='Myanmar'></span> Myanmar",
				"Namibia": "<span class='flag flag-NA' title='Namibia'></span> Namibia",
				"Nauru": "<span class='flag flag-NR' title='Nauru'></span> Nauru",
				"Nepal": "<span class='flag flag-NP' title='Nepal'></span> Nepal",
				"Netherlands": "<span class='flag flag-NL' title='Netherlands'></span> Netherlands",
				"New Caledonia": "<span class='flag flag-NC' title='New Caledonia'></span> New Caledonia",
				"New Zealand": "<span class='flag flag-NZ' title='New Zealand'></span> New Zealand",
				"Nicaragua": "<span class='flag flag-NI' title='Nicaragua'></span> Nicaragua",
				"Niger": "<span class='flag flag-NE' title='Niger'></span> Niger",
				"Nigeria": "<span class='flag flag-NG' title='Nigeria'></span> Nigeria",
				"Niue": "<span class='flag flag-NU' title='Niue'></span> Niue",
				"Norfolk Island": "<span class='flag flag-AU' title='Norfolk Island'></span> Norfolk Island",
				"Northern Mariana Islands": "<span class='flag flag-MP' title='Northern Mariana Islands'></span> Northern Mariana Islands",
				"Norway": "<span class='flag flag-NO' title='Norway'></span> Norway",
				"Oman": "<span class='flag flag-OM' title='Oman'></span> Oman",
				"Pakistan": "<span class='flag flag-PK' title='Pakistan'></span> Pakistan",
				"Palau": "<span class='flag flag-PW' title='Palau'></span> Palau",
				"Palestine|Palestinian Territory": "<span class='flag flag-PS' title='Palestine'></span> Palestine",
				"Panama": "<span class='flag flag-PA' title='Panama'></span> Panama",
				"Papua New Guinea": "<span class='flag flag-PG' title='Papua New Guinea'></span> Papua New Guinea",
				"Paraguay": "<span class='flag flag-PY' title='Paraguay'></span> Paraguay",
				"Peru": "<span class='flag flag-PE' title='Peru'></span> Peru",
				"Philippines": "<span class='flag flag-PH' title='Philippines'></span> Philippines",
				"Pitcairn": "<span class='flag flag-PN' title='Pitcairn'></span> Pitcairn",
				"Poland": "<span class='flag flag-PL' title='Poland'></span> Poland",
				"Portugal": "<span class='flag flag-PT' title='Portugal'></span> Portugal",
				"Puerto Rico": "<span class='flag flag-PR' title='Puerto Rico'></span> Puerto Rico",
				"Qatar": "<span class='flag flag-QA' title='Qatar'></span> Qatar",
				"Reunion|Réunion": "<span class='flag flag-RE' title='Reunion'></span> Reunion",
				"Romania": "<span class='flag flag-RO' title='Romania'></span> Romania",
				"Russian Federation": "<span class='flag flag-RU' title='Russian Federation'></span> Russian Federation",
				"Rwanda": "<span class='flag flag-RW' title='Rwanda'></span> Rwanda",
				"Saint Barthélemy": "<span class='flag flag-BL' title='Saint Barthélemy'></span> Saint Barthélemy",
				"Saint Helena|Saint Helena, Ascension, and Tristan da Cunha": "<span class='flag flag-SH' title='Saint Helena, Ascension, and Tristan da Cunha'></span> Saint Helena, Ascension, and Tristan da Cunha",
				"Saint Kitts and Nevis": "<span class='flag flag-KN' title='Saint Kitts and Nevis'></span> Saint Kitts and Nevis",
				"Saint Lucia": "<span class='flag flag-LC' title='Saint Lucia'></span> Saint Lucia",
				"Saint Martin": "<span class='flag flag-MF' title='Saint Martin'></span> Saint Martin",
				"Saint Pierre and Miquelon": "<span class='flag flag-PM' title='Saint Pierre and Miquelon'></span> Saint Pierre and Miquelon",
				"Saint Vincent and the Grenadines": "<span class='flag flag-VC' title='Saint Vincent and the Grenadines'></span> Saint Vincent and the Grenadines",
				"Samoa": "<span class='flag flag-WS' title='Samoa'></span> Samoa",
				"San Marino": "<span class='flag flag-SM' title='San Marino'></span> San Marino",
				"Sao Tome and Principe": "<span class='flag flag-ST' title='Sao Tome and Principe'></span> Sao Tome and Principe",
				"Satellite Provider":  "<span class='flag flag-A2' title='Satellite Provider'></span> Satellite Provider",
				"Satellite Provider": "<span class='flag flag-A2' title='Satellite Provider'></span> Satellite Provider",
				"Saudi Arabia": "<span class='flag flag-SA' title='Saudi Arabia'></span> Saudi Arabia",
				"Senegal": "<span class='flag flag-SN' title='Senegal'></span> Senegal",
				"Serbia": "<span class='flag flag-RS' title='Serbia'></span> Serbia",
				"Seychelles": "<span class='flag flag-SC' title='Seychelles'></span> Seychelles",
				"Sierra Leone": "<span class='flag flag-SL' title='Sierra Leone'></span> Sierra Leone",
				"Singapore": "<span class='flag flag-SG' title='Singapore'></span> Singapore",
				"Sint Maarten": "<span class='flag flag-SX' title='Sint Maarten'></span> Sint Maarten",
				"Slovakia": "<span class='flag flag-SK' title='Slovakia'></span> Slovakia",
				"Slovenia": "<span class='flag flag-SI' title='Slovenia'></span> Slovenia",
				"Solomon Islands": "<span class='flag flag-SB' title='Solomon Islands'></span> Solomon Islands",
				"Somalia": "<span class='flag flag-SO' title='Somalia'></span> Somalia",
				"South Africa": "<span class='flag flag-ZA' title='South Africa'></span> South Africa",
				"South Korea|Korea, Republic of": "<span class='flag flag-KR' title='South Korea'></span> South Korea",
				"South Sudan": "<span class='flag flag-SS' title='South Sudan'></span> South Sudan",
				"Spain": "<span class='flag flag-ES' title='Spain'></span> Spain",
				"Sri Lanka": "<span class='flag flag-LK' title='Sri Lanka'></span> Sri Lanka",
				"Sudan": "<span class='flag flag-SD' title='Sudan'></span> Sudan",
				"Suriname": "<span class='flag flag-SR' title='Suriname'></span> Suriname",
				"Svalbard and Jan Mayen": "<span class='flag flag-SJ' title='Svalbard and Jan Mayen'></span> Svalbard and Jan Mayen",
				"Swaziland": "<span class='flag flag-SZ' title='Swaziland'></span> Swaziland",
				"Sweden": "<span class='flag flag-SE' title='Sweden'></span> Sweden",
				"Switzerland": "<span class='flag flag-CH' title='Switzerland'></span> Switzerland",
				"Syrian Arab Republic|Syria": "<span class='flag flag-SY' title='Syria'></span> Syria",
				"Taiwan": "<span class='flag flag-TW' title='Taiwan'></span> Taiwan",
				"Tajikistan": "<span class='flag flag-TJ' title='Tajikistan'></span> Tajikistan",
				"Tanzania": "<span class='flag flag-TZ' title='Tanzani'></span> Tanzania",
				"Thailand": "<span class='flag flag-TH' title='Thailand'></span> Thailand",
				"The Democratic Republic of the Congo": "<span class='flag flag-CD' title='The Democratic Republic of the Congo'></span> The Democratic Republic of the Congo",
				"Timor-Leste": "<span class='flag flag-TL' title='Timor-Leste'></span> Timor-Leste",
				"Togo": "<span class='flag flag-TG' title='Togo'></span> Togo",
				"Tokelau": "<span class='flag flag-TK' title='Tokelau'></span> Tokelau",
				"Tonga": "<span class='flag flag-TO' title='Tonga'></span> Tonga",
				"Trinidad and Tobago": "<span class='flag flag-TT' title='Trinidad and Tobago'></span> Trinidad and Tobago",
				"Tunisia": "<span class='flag flag-TN' title='Tunisia'></span> Tunisia",
				"Turkey": "<span class='flag flag-TR' title='Turkey'></span> Turkey",
				"Turkmenistan": "<span class='flag flag-TM' title='Turkmenistan'></span> Turkmenistan",
				"Turks and Caicos Islands": "<span class='flag flag-TC' title='Turks and Caicos Islands'></span> Turks and Caicos Islands",
				"Tuvalu": "<span class='flag flag-TV' title='Tuvalu'></span> Tuvalu",
				"U.S. Virgin Islands": "<span class='flag flag-VI' title='U.S. Virgin Islands'></span> U.S. Virgin Islands",
				"Uganda": "<span class='flag flag-UG' title='Uganda'></span> Uganda",
				"Ukraine": "<span class='flag flag-UA' title='Ukraine'></span> Ukraine",
				"United Arab Emirates": "<span class='flag flag-AE' title='United Arab Emirates'></span> United Arab Emirates",
				"United Kingdom": "<span class='flag flag-GB' title='United Kingdom'></span> United Kingdom",
				"United States Minor Outlying Islands": "<span class='flag flag-UM' title='United States Minor Outlying Islands'></span> United States Minor Outlying Islands",
				"United States": "<span class='flag flag-US' title='United States'></span> United States",
				"Unknown": "<span class='flag flag-XX' title='Unknown'></span> Unknown",
				"Uruguay": "<span class='flag flag-UY' title='Uruguay'></span> Uruguay",
				"Uzbekistan": "<span class='flag flag-UZ' title='Uzbekistan'></span> Uzbekistan",
				"Vanuatu": "<span class='flag flag-VU' title='Vanuatu'></span> Vanuatu",
				"Venezuela": "<span class='flag flag-VE' title='Venezuela'></span> Venezuela",
				"Vietnam": "<span class='flag flag-VN' title='Vietnam'></span> Vietnam",
				"Virgin Islands, U.S.": "<span class='flag flag-VI' title='Virgin Islands, U.S.'></span> Virgin Islands, U.S.",
				"Wallis and Futuna": "<span class='flag flag-WF' title='Wallis and Futuna'></span> Wallis and Futuna",
				"Western Sahara": "<span class='flag flag-EH' title='Western Sahara'></span> Western Sahara",
				"Yemen": "<span class='flag flag-YE' title='Yemen'></span> Yemen",
				"Zambia": "<span class='flag flag-ZM' title='Zambia'></span> Zambia",
				"Zimbabwe": "<span class='flag flag-ZW' title='Zimbabwe'></span> Zimbabwe",
				"Anarchist": "<span class='flag flag-t_AN' title='Anarchist'></span> Anarchist",
				"Anarcho-Capitalist": "<span class='flag flag-t_AC' title='Anarcho-Capitalist'></span> Anarcho-Capitalist",
				"Black Nationalist|Black Lives Matter": "<span class='flag flag-t_BL' title='Black Nationalist'></span> Black Nationalist / Black Lives Matter",
				"Catalonia": "<span class='flag flag-t_CT' title='Catalonia'></span> Catalonia",
				"Commie|Communist": "<span class='flag flag-t_CM' title='Commie'></span> Commie / Communist",
				"Confederate": "<span class='flag flag-t_CF' title='Confederate'></span> Confederate",
				"Democrat": "<span class='flag flag-t_DM' title='Democrat'></span> Democrat",
				"Europe|European": "<span class='flag flag-t_EU' title='European'></span> Europe / European",
				"Fascist": "<span class='flag flag-t_FC' title='Fascist'></span> Fascist",
				"Gadsden": "<span class='flag flag-t_GN' title='Gadsden'></span> Gadsden",
				"Gay|LGBT": "<span class='flag flag-t_GY' title='Gay'></span> Gay / LGBT",
				"Hippie": "<span class='flag flag-t_PC' title='Hippie'></span> Hippie",
				"Jihadi": "<span class='flag flag-t_JH' title='Jihadi'></span> Jihadi",
				"Kekistani": "<span class='flag flag-t_KN' title='Kekistani'></span> Kekistani",
				"Muslim": "<span class='flag flag-t_MF' title='Muslim'></span> Muslim",
				"National Bolshevik": "<span class='flag flag-t_NB' title='National Bolshevik'></span> National Bolshevik",
				"NATO": "<span class='flag flag-t_NT' title='NATO'></span> NATO",
				"Nazi": "<span class='flag flag-t_NZ' title='Nazi'></span> Nazi",
				"Obama": "Obama",
				"Pirate": "<span class='flag flag-t_PR' title='Pirate'></span> Pirate",
				"Rebel": "Rebel",
				"Republican": "<span class='flag flag-t_RE' title='Republican'></span> Republican",
				"Templar|DEUS VULT": "<span class='flag flag-t_TM' title='Templar / DEUS VULT'></span> Templar / DEUS VULT",
				"Texan": "Texan",
				"Task Force Z": "<span class='flag flag-t_MZ' title='Task Force Z'></span> Task Force Z",
				"Tree Hugger": "<span class='flag flag-t_TR' title='Tree Hugger'></span> Tree Hugger",
				"United Nations": "<span class='flag flag-t_UN' title='United Nations'></span> United Nations",
				"White Supremacist": "<span class='flag flag-t_WP' title='White Supremacist'></span> White Supremacist",
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
				where.append("timestamp >= %s")
				replacements.append(int(query.get("min_date")))
			except ValueError:
				pass

		if query.get("max_date", 0):
			try:
				replacements.append(int(query.get("max_date")))
				where.append("timestamp < %s")
			except ValueError:
				pass

		if query.get("country_name", None):

			# Separate merged names
			country_names = []
			for country_name in query["country_name"]:
				country_name = country_name.split("|")
				for c in country_name:
					country_names.append(c)

			where.append("country_name IN %s")

			replacements.append(tuple(country_names))


		sql_query = ("SELECT " + ",".join(self.return_cols) +
					 " FROM posts_" + self.prefix +
					 " LEFT JOIN posts_" + self.prefix + "_deleted" +
					 " ON posts_" + self.prefix + ".id_seq = posts_" + self.prefix + "_deleted.id_seq" \
					 " WHERE board = %s ")

		# Exclude deleted posts
		if not query.get("get_deleted"):
			where.append("posts_%s_deleted.id_seq IS NULL" % self.prefix)

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
					sql_query = "SELECT * FROM (" + sql_query + " AND id IN " + valid_query_ids + ") ORDER BY timestamp ASC"

				else:
					self.dataset.update_status("No 4chan post IDs inserted.")
					return None

			except ValueError:
				pass

		else:
			sql_query += " ORDER BY timestamp ASC"

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

		# and we'll already save some stuff for hte postgres query
		postgres_where = []
		postgres_replacements = []
		join = ""
		postgres_join = ""

		# Option wether to use sphinx for text searches
		use_sphinx = config.get('DATASOURCES').get("4chan", {}).get("use_sphinx", True)

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

		# Limit to posts of a certain board
		board = None
		if query.get("board", None) and query["board"] != "*":
			where.append("board = %s")
			replacements.append(query["board"])
			postgres_where.append("board = %s")
			postgres_replacements.append(query["board"])
			
		if use_sphinx:
			# escape full text matches and convert quotes
			if query.get("body_match", None):
				match.append("@body " + self.convert_for_sphinx(query["body_match"]))

			if query.get("subject_match", None):
				match.append("@subject " + self.convert_for_sphinx(query["subject_match"]))
		else:
			if query.get("body_match", None):
				where.append("lower(body) LIKE %s")
				replacements.append("%" + query["body_match"] + "%")
			if query.get("subject_match", None):
				where.append("lower(subject) LIKE %s")
				replacements.append("%" + query["subject_match"] + "%")

		# handle country names through sphinx
		if query.get("country_name", None) and not query.get("check_dense_country", None):
			where.append("country_name IN %s")
			replacements.append(tuple(query.get("country_name")))

		# both possible FTS parameters go in one MATCH() operation
		if match and use_sphinx:
			where.append("MATCH(%s)")
			replacements.append(" ".join(match))

		# query Sphinx
		self.dataset.update_status("Searching for matches")

		where = " AND ".join(where)

		if use_sphinx:
			posts = self.fetch_sphinx(where, replacements)
		# Query the postgres table immediately if we're not using sphinx.
		else:
			columns = ", ".join(self.return_cols)
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while fetching post data")

			# Join on the posts_{datasource}_deleted table so we can also retrieve whether the post was deleted
			join = " LEFT JOIN posts_%s_deleted ON posts_%s.id_seq = posts_%s_deleted.id_seq " % tuple([self.prefix] * 3)
			
			# Duplicate code, but will soon be changed anyway...
			if not query.get("get_deleted"):
				where += " AND posts_%s_deleted.id_seq IS NULL" % self.prefix

			query = "SELECT " + columns + "FROM posts_" + self.prefix + join + " WHERE " + where + " ORDER BY id ASC"
			posts = self.db.fetchall_interruptable(self.queue, query, replacements)

		if posts is None:
			return posts
		elif len(posts) == 0:
			# no results
			self.dataset.update_status("Query finished, but no results were found.")
			return None

		# we don't need to do further processing if we didn't use sphinx or don't have to check for deleted posts
		if not use_sphinx or query.get("deleted"):
			return posts

		# else we query the posts database
		self.dataset.update_status("Found %i initial matches. Collecting post data" % len(posts))
		datafetch_start = time.time()
		self.log.info("Collecting post data from database")
		columns = ", ".join(self.return_cols)

		# Do a JOIN so we can check for deleted posts.
		postgres_join = " LEFT JOIN posts_%s_deleted ON posts_%s.id_seq = posts_%s_deleted.id_seq " % tuple([self.prefix] * 3)
		if not query.get("get_deleted"):
			postgres_where.append("posts_%s_deleted.id_seq IS NULL" % self.prefix)

		posts_full = self.fetch_posts(tuple([post["post_id"] for post in posts]), join=postgres_join, where=postgres_where, replacements=postgres_replacements)
		
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

	def fetch_posts(self, post_ids, join="", where=None, replacements=None):
		"""
		Fetch post data from database

		:param list post_ids:  List of post IDs to return data for
		:param join, str: A potential JOIN statement
		:param where, list: A potential WHERE statemement
		:param replacements, list: The values to add in the JOIN and WHERE statements
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

		query = "SELECT " + columns + " FROM posts_" + self.prefix + " " + join + " WHERE " + " AND ".join(
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

		# Exclude deleted posts
		exclude_deleted = ""
		if self.parameters.get("get_deleted") is False:
			exclude_deleted = "AND posts_" + self.prefix + "_deleted.id_seq IS NULL"

		return self.db.fetchall_interruptable(self.queue,
			"SELECT " + columns + " FROM posts_" + self.prefix + " \
			LEFT JOIN posts_" + self.prefix + "_deleted ON posts_" + self.prefix + ".id_seq \
			 = posts_" + self.prefix + "_deleted.id_seq \
			WHERE thread_id IN %s " + exclude_deleted + " \
			ORDER BY thread_id ASC, id ASC", (thread_ids,))

	def fetch_sphinx(self, where, replacements, join=""):
		"""
		Query Sphinx for matching post IDs

		:param str where:  Drop-in WHERE clause (without the WHERE keyword) for the Sphinx query
		:param list replacements:  Values to use for parameters in the WHERE clause that should be parsed
		:param str join:  Drop-in JOIN clause (with the JOIN keyword) for the Sphinx query
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
			sql = "SELECT thread_id, post_id FROM `" + self.prefix + "_posts` " + join + " WHERE " + where + " LIMIT 5000000 OPTION max_matches = 5000000, ranker = none, boolean_simplify = 1, sort_method = kbuffer, cutoff = 5000000"
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
			user=config.get('DB_USER'),
			password=config.get('DB_PASSWORD'),
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
		if not user.is_admin and not user.get_value("4chan.can_query_without_keyword", False) and not query.get("body_match", None) and not query.get("subject_match", None) and query.get("search_scope",	"") != "random-sample":
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
