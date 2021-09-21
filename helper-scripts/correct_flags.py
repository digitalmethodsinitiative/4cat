"""

Script to set all the flags in the correct manner for a /pol/ dataset.

"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger

import csv
import json

PATH_TO_4PLEBS_DUMP = None

if not PATH_TO_4PLEBS_DUMP:
	print("You must provide a path to a json file with post ID: troll_code key/value pairs.")
	quit()

print("Extracting posts with a troll flag from the 4plebs dump.")
troll_flags = {}
troll_names = {
	"AC": "Anarcho-Capitalist",
	"AN": "Anarchist",
	"BL": "Black Nationalist",
	"CF": "Confederate",
	"CT": "Catalonia",
	"CM": "Communist",
	"DM": "Democrat",
	"EU": "European",
	"FC": "Fascist",
	"GN": "Gadsden",
	"GY": "Gay",
	"JH": "Jihadi",
	"KP": "North Korea",
	"KN": "Kekistani",
	"MF": "Muslim",
	"NB": "National Bolshevik",
	"NZ": "Nazi",
	"OB": "Obama",
	"PC": "Hippie",
	"PR": "Pirate",
	"RB": "Rebel",
	"RE": "Republican",
	"RP": "Libertarian",
	"TM": "Templar",
	"TP": "Tea Partier",
	"TR": "Tree Hugger",
	"TX": "Texan",
	"UN": "United Nations",
	"WP": "White Supremacist"
}

with open(PATH_TO_4PLEBS_DUMP, encoding="utf-8") as in_csv:

	fieldnames = ("num", "subnum", "thread_num", "op", "timestamp", "timestamp_expired", "preview_orig", "preview_w", "preview_h", "media_filename", "media_w", "media_h", "media_size", "media_hash", "media_orig", "spoiler", "deleted", "capcode", "email", "name", "trip", "title", "comment", "sticky", "locked", "poster_hash", "poster_country", "exif")

	reader = csv.DictReader(in_csv, fieldnames=fieldnames, doublequote=False, escapechar="\\", strict=True)
	count = 0

	for post in reader:
		count += 1
		if "exif" in post:

			if "troll_country" in post["exif"]:

				troll_json = json.loads(post["exif"])
				troll_code = troll_json["troll_country"]
				troll_name = troll_conversion[troll_code]

				if troll_name not in troll_flags:
					troll_flags[troll_name] = []

				troll_flags[troll_name].append(int(post["num"]))

		if count % 100000 == 0:
			for k, v in troll_flags.items():
				print(k, str(len(v)))

with open("troll_flags.json", "w", encoding="utf-8") as out_json:
	json.dump(troll_flags, out_json)


logger = Logger()
db = Database(logger=logger, appname="queue-dump")

# Loop through the troll country data from the 4plebs dump
print("Updating ambiguous troll flags using the 4plebs dump.")
for k, v in troll_flags.items():
	
	for troll_code, troll_name in troll_names.items():

		troll_ids = tuple([int(k) for k, v in troll_flags.items() if v == troll_code])

		query_update_ambiguous_troll_flag = ("""
			UPDATE posts_4chan
			SET country_name = '%s', country_code = '%s'
			WHERE id IN %s
			AND board = 'pol'
			AND ((country_name IS NULL OR country_name = '') AND (country_code IS NULL OR country_code = ''));
		""" % (troll_name, 't_' + troll_code, troll_ids))
		db.execute(query_update_ambiguous_troll_flag)
		db.commit()

# First we have to fill in the empty troll country data.
# These are stored in the `unsorted_data` columns, with
# `board_flags` as the country code and `flag_name` as country name.
print("Moving troll flags from `unsorted_data` to `country_code` and `country_name`.")

query_move_troll_flags = """
		UPDATE posts_4chan
		SET country_code = unsorted_data::json#>>'{board_flag}',
			country_name = unsorted_data::json#>>'{flag_name}',
			unsorted_data = unsorted_data::jsonb - '{board_flag, flag_name}'::text[]
		WHERE board='pol'
		AND (country_name = '') IS NOT FALSE
		AND (country_code = '') IS NOT FALSE;
		"""

db.execute(query_move_troll_flags)

# For the pre 15 December 2014 posts, only static country flags were available.
# These included both troll flags and actual flags.
# So here we can simply set the country names according to those static codes.
print("Adding `country_name` values for posts before 15 December 2014, when only geoflags were available.")

query_update_old_flags = """
		UPDATE posts_4chan
		SET country_name =   
		CASE
			WHEN country_code = 'AC' THEN 'Anarcho-Capitalist'
			WHEN country_code = 'AN' THEN 'Anarchist'
			WHEN country_code = 'BL' THEN 'Black Nationalist'
			WHEN country_code = 'CF' THEN 'Confederate'
			WHEN country_code = 'CM' THEN 'Communist'
			WHEN country_code = 'DM' THEN 'Democrat'
			WHEN country_code = 'EU' THEN 'European'
			WHEN country_code = 'GN' THEN 'Gadsden'
			WHEN country_code = 'GY' THEN 'Gay'
			WHEN country_code = 'IL' THEN 'Israel'
			WHEN country_code = 'JH' THEN 'Jihadi'
			WHEN country_code = 'KP' THEN 'North Korea'
			WHEN country_code = 'MF' THEN 'Muslim'
			WHEN country_code = 'NB' THEN 'National Bolshevik'
			WHEN country_code = 'NZ' THEN 'Nazi'
			WHEN country_code = 'OB' THEN 'Obama'
			WHEN country_code = 'PC' THEN 'Hippie'
			WHEN country_code = 'PR' THEN 'Pirate'
			WHEN country_code = 'RB' THEN 'Rebel'
			WHEN country_code = 'RE' THEN 'Republican'
			WHEN country_code = 'RP' THEN 'Libertarian'
			WHEN country_code = 'TM' THEN 'Templar'
			WHEN country_code = 'TP' THEN 'Tea Partier'
			WHEN country_code = 'TR' THEN 'Tree Hugger'
			WHEN country_code = 'TX' THEN 'Texan'
			WHEN country_code = 'UN' THEN 'United Nations'
			WHEN country_code = 'US' THEN 'United States'
			WHEN country_code = 'WP' THEN 'White Supremacist'
			ELSE ''
		END 
		WHERE board='pol'
		AND timestamp < 1418515200
		AND (country_name = '') IS NOT FALSE;
		"""

db.execute(query_update_old_flags)
db.commit()

# After 15 December 2014 and before 13 June 2017, only geoflags were available, so no troll flags, no conflicts.
print("Adding `country_name` values for posts after 15 December 2014 and before 14 July 2017.")

query_update_country_flags = """
		UPDATE posts_4chan
		SET country_name =
		CASE
			WHEN country_code = 'A2' THEN 'Satellite Provider'
			WHEN country_code = 'AD' THEN 'Andorra'
			WHEN country_code = 'AE' THEN 'United Arab Emirates'
			WHEN country_code = 'AF' THEN 'Afghanistan'
			WHEN country_code = 'AG' THEN 'Antigua and Barbuda'
			WHEN country_code = 'AI' THEN 'Anguilla'
			WHEN country_code = 'AL' THEN 'Albania'
			WHEN country_code = 'AM' THEN 'Armenia'
			WHEN country_code = 'AO' THEN 'Angola'
			WHEN country_code = 'AP' THEN 'Asia/Pacific Region'
			WHEN country_code = 'AQ' THEN 'Antarctica'
			WHEN country_code = 'AS' THEN 'American Samoa''s'
			WHEN country_code = 'AT' THEN 'Austria'
			WHEN country_code = 'AU' THEN 'Australia'
			WHEN country_code = 'AU' THEN 'Norfolk Island'
			WHEN country_code = 'AW' THEN 'Aruba'
			WHEN country_code = 'AX' THEN 'Aland'
			WHEN country_code = 'AZ' THEN 'Azerbaijan'
			WHEN country_code = 'BA' THEN 'Bosnia and Herzegovina'
			WHEN country_code = 'BB' THEN 'Barbados'
			WHEN country_code = 'BD' THEN 'Bangladesh'
			WHEN country_code = 'BE' THEN 'Belgium'
			WHEN country_code = 'BF' THEN 'Burkina Faso'
			WHEN country_code = 'BG' THEN 'Bulgaria'
			WHEN country_code = 'BH' THEN 'Bahrain'
			WHEN country_code = 'BI' THEN 'Burundi'
			WHEN country_code = 'BJ' THEN 'Benin'
			WHEN country_code = 'BL' THEN 'Saint Barthélemy'
			WHEN country_code = 'BM' THEN 'Bermuda'
			WHEN country_code = 'BN' THEN 'Brunei'
			WHEN country_code = 'BO' THEN 'Bolivia'
			WHEN country_code = 'BQ' THEN 'Bonaire, Sint Eustatius and Saba'
			WHEN country_code = 'BR' THEN 'Brazil'
			WHEN country_code = 'BS' THEN 'Bahamas'
			WHEN country_code = 'BT' THEN 'Bhutan'
			WHEN country_code = 'BV' THEN 'Bouvet Island'
			WHEN country_code = 'BW' THEN 'Botswana'
			WHEN country_code = 'BY' THEN 'Belarus'
			WHEN country_code = 'BZ' THEN 'Belize'
			WHEN country_code = 'CA' THEN 'Canada'
			WHEN country_code = 'CC' THEN 'Cocos (Keeling) Islands'
			WHEN country_code = 'CD' THEN 'Congo'
			WHEN country_code = 'CD' THEN 'The Democratic Republic of the Congo'
			WHEN country_code = 'CF' THEN 'Central African Republic'
			WHEN country_code = 'CG' THEN 'Congo'
			WHEN country_code = 'CH' THEN 'Switzerland'
			WHEN country_code = 'CI' THEN 'Côte d''Ivoire'
			WHEN country_code = 'CK' THEN 'Cook Islands'
			WHEN country_code = 'CL' THEN 'Chile'
			WHEN country_code = 'CM' THEN 'Cameroon'
			WHEN country_code = 'CN' THEN 'China'
			WHEN country_code = 'CO' THEN 'Colombia'
			WHEN country_code = 'CR' THEN 'Costa Rica'
			WHEN country_code = 'CU' THEN 'Cuba'
			WHEN country_code = 'CV' THEN 'Cape Verde'
			WHEN country_code = 'CW' THEN 'Curaçao'
			WHEN country_code = 'CX' THEN 'Christmas Island'
			WHEN country_code = 'CY' THEN 'Cyprus'
			WHEN country_code = 'CZ' THEN 'Czech Republic'
			WHEN country_code = 'DE' THEN 'Germany'
			WHEN country_code = 'DJ' THEN 'Djibouti'
			WHEN country_code = 'DK' THEN 'Denmark'
			WHEN country_code = 'DM' THEN 'Dominica'
			WHEN country_code = 'DO' THEN 'Dominican Republic'
			WHEN country_code = 'DZ' THEN 'Algeria'
			WHEN country_code = 'EC' THEN 'Ecuador'
			WHEN country_code = 'EE' THEN 'Estonia'
			WHEN country_code = 'EG' THEN 'Egypt'
			WHEN country_code = 'EH' THEN 'Western Sahara'
			WHEN country_code = 'ER' THEN 'Eritrea'
			WHEN country_code = 'ES' THEN 'Spain'
			WHEN country_code = 'ET' THEN 'Ethiopia'
			WHEN country_code = 'EU' THEN 'European'
			WHEN country_code = 'FI' THEN 'Finland'
			WHEN country_code = 'FJ' THEN 'Fiji Islands'
			WHEN country_code = 'FK' THEN 'Falkland Islands'
			WHEN country_code = 'FM' THEN 'Federated States of Micronesia'
			WHEN country_code = 'FO' THEN 'Faroe Islands'
			WHEN country_code = 'FR' THEN 'France'
			WHEN country_code = 'GA' THEN 'Gabon'
			WHEN country_code = 'GB' THEN 'United Kingdom'
			WHEN country_code = 'GD' THEN 'Grenada'
			WHEN country_code = 'GE' THEN 'Georgia'
			WHEN country_code = 'GG' THEN 'Guernsey'
			WHEN country_code = 'GH' THEN 'Ghana'
			WHEN country_code = 'GI' THEN 'Gibraltar'
			WHEN country_code = 'GL' THEN 'Greenland'
			WHEN country_code = 'GM' THEN 'Gambia'
			WHEN country_code = 'GN' THEN 'Guinea'
			WHEN country_code = 'GP' THEN 'Guadeloupe'
			WHEN country_code = 'GQ' THEN 'Equatorial Guinea'
			WHEN country_code = 'GR' THEN 'Greece'
			WHEN country_code = 'GT' THEN 'Guatemala'
			WHEN country_code = 'GU' THEN 'Guam'
			WHEN country_code = 'GW' THEN 'Guinea-Bissau'
			WHEN country_code = 'GY' THEN 'Guyana'
			WHEN country_code = 'HK' THEN 'Hong Kong'
			WHEN country_code = 'HN' THEN 'Honduras'
			WHEN country_code = 'HR' THEN 'Croatia'
			WHEN country_code = 'HT' THEN 'Haiti'
			WHEN country_code = 'HU' THEN 'Hungary'
			WHEN country_code = 'ID' THEN 'Indonesia'
			WHEN country_code = 'IE' THEN 'Ireland'
			WHEN country_code = 'IL' THEN 'Israel'
			WHEN country_code = 'IM' THEN 'Isle of Man'
			WHEN country_code = 'IN' THEN 'India'
			WHEN country_code = 'IO' THEN 'British Indian Ocean Territory'
			WHEN country_code = 'IQ' THEN 'Iraq'
			WHEN country_code = 'IR' THEN 'Iran'
			WHEN country_code = 'IS' THEN 'Iceland'
			WHEN country_code = 'IT' THEN 'Italy'
			WHEN country_code = 'JE' THEN 'Jersey'
			WHEN country_code = 'JM' THEN 'Jamaica'
			WHEN country_code = 'JO' THEN 'Jordan'
			WHEN country_code = 'JP' THEN 'Japan'
			WHEN country_code = 'KE' THEN 'Kenya'
			WHEN country_code = 'KG' THEN 'Kyrgyzstan'
			WHEN country_code = 'KH' THEN 'Cambodia'
			WHEN country_code = 'KI' THEN 'Kiribati'
			WHEN country_code = 'KM' THEN 'Comoros'
			WHEN country_code = 'KN' THEN 'Saint Kitts and Nevis'
			WHEN country_code = 'KR' THEN 'South Korea'
			WHEN country_code = 'KW' THEN 'Kuwait'
			WHEN country_code = 'KY' THEN 'Cayman Islands'
			WHEN country_code = 'KZ' THEN 'Kazakhstan'
			WHEN country_code = 'LA' THEN 'Laos'
			WHEN country_code = 'LB' THEN 'Lebanon'
			WHEN country_code = 'LC' THEN 'Saint Lucia'
			WHEN country_code = 'LI' THEN 'Liechtenstein'
			WHEN country_code = 'LK' THEN 'Sri Lanka'
			WHEN country_code = 'LR' THEN 'Liberia'
			WHEN country_code = 'LS' THEN 'Lesotho'
			WHEN country_code = 'LT' THEN 'Lithuania'
			WHEN country_code = 'LU' THEN 'Luxembourg'
			WHEN country_code = 'LV' THEN 'Latvia'
			WHEN country_code = 'LY' THEN 'Libya'
			WHEN country_code = 'MA' THEN 'Morocco'
			WHEN country_code = 'MC' THEN 'Monaco'
			WHEN country_code = 'MD' THEN 'Moldova'
			WHEN country_code = 'ME' THEN 'Montenegro'
			WHEN country_code = 'MF' THEN 'Saint Martin'
			WHEN country_code = 'MG' THEN 'Madagascar'
			WHEN country_code = 'MH' THEN 'Marshall Islands'
			WHEN country_code = 'MK' THEN 'Macedonia'
			WHEN country_code = 'ML' THEN 'Mali'
			WHEN country_code = 'MM' THEN 'Myanmar'
			WHEN country_code = 'MN' THEN 'Mongolia'
			WHEN country_code = 'MO' THEN 'Macao'
			WHEN country_code = 'MP' THEN 'Northern Mariana Islands'
			WHEN country_code = 'MQ' THEN 'Martinique'
			WHEN country_code = 'MR' THEN 'Mauritania'
			WHEN country_code = 'MS' THEN 'Montserrat'
			WHEN country_code = 'MT' THEN 'Malta'
			WHEN country_code = 'MU' THEN 'Mauritius'
			WHEN country_code = 'MV' THEN 'Maldives'
			WHEN country_code = 'MW' THEN 'Malawi'
			WHEN country_code = 'MX' THEN 'Mexico'
			WHEN country_code = 'MY' THEN 'Malaysia'
			WHEN country_code = 'MZ' THEN 'Mozambique'
			WHEN country_code = 'NA' THEN 'Namibia'
			WHEN country_code = 'NC' THEN 'New Caledonia'
			WHEN country_code = 'NE' THEN 'Niger'
			WHEN country_code = 'NF' THEN 'Norfolk Island'
			WHEN country_code = 'NG' THEN 'Nigeria'
			WHEN country_code = 'NI' THEN 'Nicaragua'
			WHEN country_code = 'NL' THEN 'Netherlands'
			WHEN country_code = 'NO' THEN 'Norway'
			WHEN country_code = 'NP' THEN 'Nepal'
			WHEN country_code = 'NR' THEN 'Nauru'
			WHEN country_code = 'NU' THEN 'Niue'
			WHEN country_code = 'NZ' THEN 'New Zealand'
			WHEN country_code = 'OM' THEN 'Oman'
			WHEN country_code = 'PA' THEN 'Panama'
			WHEN country_code = 'PE' THEN 'Peru'
			WHEN country_code = 'PF' THEN 'French Polynesia'
			WHEN country_code = 'PG' THEN 'Papua New Guinea'
			WHEN country_code = 'PH' THEN 'Philippines'
			WHEN country_code = 'PK' THEN 'Pakistan'
			WHEN country_code = 'PL' THEN 'Poland'
			WHEN country_code = 'PM' THEN 'Saint Pierre and Miquelon'
			WHEN country_code = 'PN' THEN 'Pitcairn'
			WHEN country_code = 'PR' THEN 'Puerto Rico'
			WHEN country_code = 'PS' THEN 'Palestine'
			WHEN country_code = 'PS' THEN 'Palestine'
			WHEN country_code = 'PT' THEN 'Portugal'
			WHEN country_code = 'PW' THEN 'Palau'
			WHEN country_code = 'PY' THEN 'Paraguay'
			WHEN country_code = 'QA' THEN 'Qatar'
			WHEN country_code = 'RE' THEN 'Réunion'
			WHEN country_code = 'RO' THEN 'Romania'
			WHEN country_code = 'RS' THEN 'Serbia'
			WHEN country_code = 'RU' THEN 'Russian Federation'
			WHEN country_code = 'RW' THEN 'Rwanda'
			WHEN country_code = 'SA' THEN 'Saudi Arabia'
			WHEN country_code = 'SB' THEN 'Solomon Islands'
			WHEN country_code = 'SC' THEN 'Seychelles'
			WHEN country_code = 'SD' THEN 'Sudan'
			WHEN country_code = 'SE' THEN 'Sweden'
			WHEN country_code = 'SG' THEN 'Singapore'
			WHEN country_code = 'SH' THEN 'Saint Helena, Ascension, and Tristan da Cunha'
			WHEN country_code = 'SI' THEN 'Slovenia'
			WHEN country_code = 'SJ' THEN 'Svalbard and Jan Mayen'
			WHEN country_code = 'SK' THEN 'Slovakia'
			WHEN country_code = 'SL' THEN 'Sierra Leone'
			WHEN country_code = 'SM' THEN 'San Marino'
			WHEN country_code = 'SN' THEN 'Senegal'
			WHEN country_code = 'SO' THEN 'Somalia'
			WHEN country_code = 'SR' THEN 'Suriname'
			WHEN country_code = 'SS' THEN 'South Sudan'
			WHEN country_code = 'ST' THEN 'Sao Tome and Principe'
			WHEN country_code = 'SV' THEN 'El Salvador'
			WHEN country_code = 'SX' THEN 'Sint Maarten'
			WHEN country_code = 'SY' THEN 'Syria'
			WHEN country_code = 'SZ' THEN 'Swaziland'
			WHEN country_code = 'TC' THEN 'Turks and Caicos Islands'
			WHEN country_code = 'TD' THEN 'Chad'
			WHEN country_code = 'TG' THEN 'Togo'
			WHEN country_code = 'TH' THEN 'Thailand'
			WHEN country_code = 'TJ' THEN 'Tajikistan'
			WHEN country_code = 'TK' THEN 'Tokelau'
			WHEN country_code = 'TL' THEN 'Timor-Leste'
			WHEN country_code = 'TM' THEN 'Turkmenistan'
			WHEN country_code = 'TN' THEN 'Tunisia'
			WHEN country_code = 'TO' THEN 'Tonga'
			WHEN country_code = 'TR' THEN 'Turkey'
			WHEN country_code = 'TT' THEN 'Trinidad and Tobago'
			WHEN country_code = 'TV' THEN 'Tuvalu'
			WHEN country_code = 'TW' THEN 'Taiwan'
			WHEN country_code = 'TZ' THEN 'Tanzani'
			WHEN country_code = 'UA' THEN 'Ukraine'
			WHEN country_code = 'UG' THEN 'Uganda'
			WHEN country_code = 'UM' THEN 'United States Minor Outlying Islands'
			WHEN country_code = 'US' THEN 'United States'
			WHEN country_code = 'UY' THEN 'Uruguay'
			WHEN country_code = 'UZ' THEN 'Uzbekistan'
			WHEN country_code = 'VA' THEN 'Holy See (Vatican City State)'
			WHEN country_code = 'VC' THEN 'Saint Vincent and the Grenadines'
			WHEN country_code = 'VE' THEN 'Venezuela'
			WHEN country_code = 'VG' THEN 'British Virgin Islands'
			WHEN country_code = 'VI' THEN 'U.S. Virgin Islands'
			WHEN country_code = 'VI' THEN 'Virgin Islands, U.S.'
			WHEN country_code = 'VN' THEN 'Vietnam'
			WHEN country_code = 'VU' THEN 'Vanuatu'
			WHEN country_code = 'WF' THEN 'Wallis and Futuna'
			WHEN country_code = 'WS' THEN 'Samoa'
			WHEN country_code = 'XK' THEN 'Kosovo'
			WHEN country_code = 'XX' THEN 'Unknown'
			WHEN country_code = 'YE' THEN 'Yemen'
			WHEN country_code = 'YT' THEN 'Mayotte'
			WHEN country_code = 'ZA' THEN 'South Africa'
			WHEN country_code = 'ZM' THEN 'Zambia'
			WHEN country_code = 'ZW' THEN 'Zimbabwe'
			ELSE country_name
			END 
		WHERE board='pol'
		AND timestamp >= 1418515200 AND timestamp < 1497312000
		AND (country_name = '') IS NOT FALSE;
		"""

db.execute(query_update_country_flags)
db.commit()

""" After 13 June 2017, both meme and troll flags were available.
We can fill in all the names of country codes that can only refer to a country or troll country.
"""

print("Settings `country_names` for posts after 13 June 2017.")

query_update_country_names = """
		UPDATE posts_4chan
		SET country_name =
		CASE
			WHEN country_code = 'A2' THEN 'Satellite Provider'
			WHEN country_code = 'AD' THEN 'Andorra'
			WHEN country_code = 'AE' THEN 'United Arab Emirates'
			WHEN country_code = 'AF' THEN 'Afghanistan'
			WHEN country_code = 'AG' THEN 'Antigua and Barbuda'
			WHEN country_code = 'AI' THEN 'Anguilla'
			WHEN country_code = 'AL' THEN 'Albania'
			WHEN country_code = 'AM' THEN 'Armenia'
			WHEN country_code = 'AO' THEN 'Angola'
			WHEN country_code = 'AP' THEN 'Asia/Pacific Region'
			WHEN country_code = 'AQ' THEN 'Antarctica'
			WHEN country_code = 'AR' THEN 'Argentina'
			WHEN country_code = 'AS' THEN 'American Samoa''s'
			WHEN country_code = 'AT' THEN 'Austria'
			WHEN country_code = 'AU' THEN 'Australia'
			WHEN country_code = 'AW' THEN 'Aruba'
			WHEN country_code = 'AX' THEN 'Aland'
			WHEN country_code = 'AZ' THEN 'Azerbaijan'
			WHEN country_code = 'BA' THEN 'Bosnia and Herzegovina'
			WHEN country_code = 'BB' THEN 'Barbados'
			WHEN country_code = 'BD' THEN 'Bangladesh'
			WHEN country_code = 'BE' THEN 'Belgium'
			WHEN country_code = 'BF' THEN 'Burkina Faso'
			WHEN country_code = 'BG' THEN 'Bulgaria'
			WHEN country_code = 'BH' THEN 'Bahrain'
			WHEN country_code = 'BI' THEN 'Burundi'
			WHEN country_code = 'BJ' THEN 'Benin'
			WHEN country_code = 'BM' THEN 'Bermuda'
			WHEN country_code = 'BN' THEN 'Brunei'
			WHEN country_code = 'BO' THEN 'Bolivia'
			WHEN country_code = 'BQ' THEN 'Bonaire, Sint Eustatius and Saba'
			WHEN country_code = 'BR' THEN 'Brazil'
			WHEN country_code = 'BS' THEN 'Bahamas'
			WHEN country_code = 'BT' THEN 'Bhutan'
			WHEN country_code = 'BV' THEN 'Bouvet Island'
			WHEN country_code = 'BW' THEN 'Botswana'
			WHEN country_code = 'BY' THEN 'Belarus'
			WHEN country_code = 'BZ' THEN 'Belize'
			WHEN country_code = 'CA' THEN 'Canada'
			WHEN country_code = 'CC' THEN 'Cocos (Keeling) Islands'
			WHEN country_code = 'CD' THEN 'Congo'
			WHEN country_code = 'CD' THEN 'The Democratic Republic of the Congo'
			WHEN country_code = 'CF' THEN 'Central African Republic'
			WHEN country_code = 'CG' THEN 'Congo'
			WHEN country_code = 'CH' THEN 'Switzerland'
			WHEN country_code = 'CI' THEN 'Côte d''Ivoire'
			WHEN country_code = 'CK' THEN 'Cook Islands'
			WHEN country_code = 'CL' THEN 'Chile'
			WHEN country_code = 'CN' THEN 'China'
			WHEN country_code = 'CO' THEN 'Colombia'
			WHEN country_code = 'CR' THEN 'Costa Rica'
			WHEN country_code = 'CU' THEN 'Cuba'
			WHEN country_code = 'CV' THEN 'Cape Verde'
			WHEN country_code = 'CW' THEN 'Curacao'
			WHEN country_code = 'CW' THEN 'Curaçao'
			WHEN country_code = 'CX' THEN 'Christmas Island'
			WHEN country_code = 'CY' THEN 'Cyprus'
			WHEN country_code = 'CZ' THEN 'Czech Republic'
			WHEN country_code = 'DE' THEN 'Germany'
			WHEN country_code = 'DJ' THEN 'Djibouti'
			WHEN country_code = 'DK' THEN 'Denmark'
			WHEN country_code = 'DO' THEN 'Dominican Republic'
			WHEN country_code = 'DZ' THEN 'Algeria'
			WHEN country_code = 'EC' THEN 'Ecuador'
			WHEN country_code = 'EE' THEN 'Estonia'
			WHEN country_code = 'EG' THEN 'Egypt'
			WHEN country_code = 'EH' THEN 'Western Sahara'
			WHEN country_code = 'ER' THEN 'Eritrea'
			WHEN country_code = 'ES' THEN 'Spain'
			WHEN country_code = 'ET' THEN 'Ethiopia'
			WHEN country_code = 'EU' THEN 'European'
			WHEN country_code = 'FI' THEN 'Finland'
			WHEN country_code = 'FJ' THEN 'Fiji Islands'
			WHEN country_code = 'FK' THEN 'Falkland Islands'
			WHEN country_code = 'FM' THEN 'Federated States of Micronesia'
			WHEN country_code = 'FO' THEN 'Faroe Islands'
			WHEN country_code = 'FR' THEN 'France'
			WHEN country_code = 'GA' THEN 'Gabon'
			WHEN country_code = 'GB' THEN 'United Kingdom'
			WHEN country_code = 'GD' THEN 'Grenada'
			WHEN country_code = 'GE' THEN 'Georgia'
			WHEN country_code = 'GF' THEN 'French Guiana'
			WHEN country_code = 'GF' THEN 'French Guiana'
			WHEN country_code = 'GG' THEN 'Guernsey'
			WHEN country_code = 'GH' THEN 'Ghana'
			WHEN country_code = 'GI' THEN 'Gibraltar'
			WHEN country_code = 'GL' THEN 'Greenland'
			WHEN country_code = 'GM' THEN 'Gambia'
			WHEN country_code = 'GP' THEN 'Guadeloupe'
			WHEN country_code = 'GQ' THEN 'Equatorial Guinea'
			WHEN country_code = 'GR' THEN 'Greece'
			WHEN country_code = 'GT' THEN 'Guatemala'
			WHEN country_code = 'GU' THEN 'Guam'
			WHEN country_code = 'GW' THEN 'Guinea-Bissau'
			WHEN country_code = 'HK' THEN 'Hong Kong'
			WHEN country_code = 'HM' THEN 'Heard Island and McDonald Islands'
			WHEN country_code = 'HN' THEN 'Honduras'
			WHEN country_code = 'HR' THEN 'Croatia'
			WHEN country_code = 'HT' THEN 'Haiti'
			WHEN country_code = 'HU' THEN 'Hungary'
			WHEN country_code = 'ID' THEN 'Indonesia'
			WHEN country_code = 'IE' THEN 'Ireland'
			WHEN country_code = 'IL' THEN 'Israel'
			WHEN country_code = 'IM' THEN 'Isle of Man'
			WHEN country_code = 'IN' THEN 'India'
			WHEN country_code = 'IO' THEN 'British Indian Ocean Territory'
			WHEN country_code = 'IQ' THEN 'Iraq'
			WHEN country_code = 'IR' THEN 'Iran'
			WHEN country_code = 'IS' THEN 'Iceland'
			WHEN country_code = 'IT' THEN 'Italy'
			WHEN country_code = 'JE' THEN 'Jersey'
			WHEN country_code = 'JM' THEN 'Jamaica'
			WHEN country_code = 'JO' THEN 'Jordan'
			WHEN country_code = 'JP' THEN 'Japan'
			WHEN country_code = 'KE' THEN 'Kenya'
			WHEN country_code = 'KG' THEN 'Kyrgyzstan'
			WHEN country_code = 'KH' THEN 'Cambodia'
			WHEN country_code = 'KI' THEN 'Kiribati'
			WHEN country_code = 'KM' THEN 'Comoros'
			WHEN country_code = 'KR' THEN 'South Korea'
			WHEN country_code = 'KW' THEN 'Kuwait'
			WHEN country_code = 'KY' THEN 'Cayman Islands'
			WHEN country_code = 'KZ' THEN 'Kazakhstan'
			WHEN country_code = 'LA' THEN 'Laos'
			WHEN country_code = 'LB' THEN 'Lebanon'
			WHEN country_code = 'LC' THEN 'Saint Lucia'
			WHEN country_code = 'LI' THEN 'Liechtenstein'
			WHEN country_code = 'LK' THEN 'Sri Lanka'
			WHEN country_code = 'LR' THEN 'Liberia'
			WHEN country_code = 'LS' THEN 'Lesotho'
			WHEN country_code = 'LT' THEN 'Lithuania'
			WHEN country_code = 'LU' THEN 'Luxembourg'
			WHEN country_code = 'LV' THEN 'Latvia'
			WHEN country_code = 'LY' THEN 'Libya'
			WHEN country_code = 'MA' THEN 'Morocco'
			WHEN country_code = 'MC' THEN 'Monaco'
			WHEN country_code = 'MD' THEN 'Moldova'
			WHEN country_code = 'ME' THEN 'Montenegro'
			WHEN country_code = 'MG' THEN 'Madagascar'
			WHEN country_code = 'MH' THEN 'Marshall Islands'
			WHEN country_code = 'MK' THEN 'Macedonia'
			WHEN country_code = 'ML' THEN 'Mali'
			WHEN country_code = 'MM' THEN 'Myanmar'
			WHEN country_code = 'MN' THEN 'Mongolia'
			WHEN country_code = 'MO' THEN 'Macao'
			WHEN country_code = 'MP' THEN 'Northern Mariana Islands'
			WHEN country_code = 'MQ' THEN 'Martinique'
			WHEN country_code = 'MR' THEN 'Mauritania'
			WHEN country_code = 'MS' THEN 'Montserrat'
			WHEN country_code = 'MT' THEN 'Malta'
			WHEN country_code = 'MU' THEN 'Mauritius'
			WHEN country_code = 'MV' THEN 'Maldives'
			WHEN country_code = 'MW' THEN 'Malawi'
			WHEN country_code = 'MX' THEN 'Mexico'
			WHEN country_code = 'MY' THEN 'Malaysia'
			WHEN country_code = 'MZ' THEN 'Mozambique'
			WHEN country_code = 'NA' THEN 'Namibia'
			WHEN country_code = 'NC' THEN 'New Caledonia'
			WHEN country_code = 'NE' THEN 'Niger'
			WHEN country_code = 'NF' THEN 'Norfolk Island'
			WHEN country_code = 'NG' THEN 'Nigeria'
			WHEN country_code = 'NI' THEN 'Nicaragua'
			WHEN country_code = 'NL' THEN 'Netherlands'
			WHEN country_code = 'NO' THEN 'Norway'
			WHEN country_code = 'NP' THEN 'Nepal'
			WHEN country_code = 'NR' THEN 'Nauru'
			WHEN country_code = 'NU' THEN 'Niue'
			WHEN country_code = 'OM' THEN 'Oman'
			WHEN country_code = 'PA' THEN 'Panama'
			WHEN country_code = 'PE' THEN 'Peru'
			WHEN country_code = 'PF' THEN 'French Polynesia'
			WHEN country_code = 'PG' THEN 'Papua New Guinea'
			WHEN country_code = 'PH' THEN 'Philippines'
			WHEN country_code = 'PK' THEN 'Pakistan'
			WHEN country_code = 'PL' THEN 'Poland'
			WHEN country_code = 'PM' THEN 'Saint Pierre and Miquelon'
			WHEN country_code = 'PN' THEN 'Pitcairn'
			WHEN country_code = 'PS' THEN 'Palestine'
			WHEN country_code = 'PT' THEN 'Portugal'
			WHEN country_code = 'PW' THEN 'Palau'
			WHEN country_code = 'PY' THEN 'Paraguay'
			WHEN country_code = 'QA' THEN 'Qatar'
			WHEN country_code = 'RO' THEN 'Romania'
			WHEN country_code = 'RS' THEN 'Serbia'
			WHEN country_code = 'RU' THEN 'Russian Federation'
			WHEN country_code = 'RW' THEN 'Rwanda'
			WHEN country_code = 'SA' THEN 'Saudi Arabia'
			WHEN country_code = 'SB' THEN 'Solomon Islands'
			WHEN country_code = 'SC' THEN 'Seychelles'
			WHEN country_code = 'SD' THEN 'Sudan'
			WHEN country_code = 'SE' THEN 'Sweden'
			WHEN country_code = 'SG' THEN 'Singapore'
			WHEN country_code = 'SH' THEN 'Saint Helena, Ascension, and Tristan da Cunha'
			WHEN country_code = 'SI' THEN 'Slovenia'
			WHEN country_code = 'SJ' THEN 'Svalbard and Jan Mayen'
			WHEN country_code = 'SK' THEN 'Slovakia'
			WHEN country_code = 'SL' THEN 'Sierra Leone'
			WHEN country_code = 'SM' THEN 'San Marino'
			WHEN country_code = 'SN' THEN 'Senegal'
			WHEN country_code = 'SO' THEN 'Somalia'
			WHEN country_code = 'SR' THEN 'Suriname'
			WHEN country_code = 'SS' THEN 'South Sudan'
			WHEN country_code = 'ST' THEN 'Sao Tome and Principe'
			WHEN country_code = 'SV' THEN 'El Salvador'
			WHEN country_code = 'SX' THEN 'Sint Maarten'
			WHEN country_code = 'SY' THEN 'Syria'
			WHEN country_code = 'SZ' THEN 'Swaziland'
			WHEN country_code = 'TC' THEN 'Turks and Caicos Islands'
			WHEN country_code = 'TD' THEN 'Chad'
			WHEN country_code = 'TG' THEN 'Togo'
			WHEN country_code = 'TH' THEN 'Thailand'
			WHEN country_code = 'TJ' THEN 'Tajikistan'
			WHEN country_code = 'TK' THEN 'Tokelau'
			WHEN country_code = 'TL' THEN 'Timor-Leste'
			WHEN country_code = 'TN' THEN 'Tunisia'
			WHEN country_code = 'TO' THEN 'Tonga'
			WHEN country_code = 'TT' THEN 'Trinidad and Tobago'
			WHEN country_code = 'TV' THEN 'Tuvalu'
			WHEN country_code = 'TW' THEN 'Taiwan'
			WHEN country_code = 'TZ' THEN 'Tanzani'
			WHEN country_code = 'UA' THEN 'Ukraine'
			WHEN country_code = 'UG' THEN 'Uganda'
			WHEN country_code = 'UM' THEN 'United States Minor Outlying Islands'
			WHEN country_code = 'US' THEN 'United States'
			WHEN country_code = 'UY' THEN 'Uruguay'
			WHEN country_code = 'UZ' THEN 'Uzbekistan'
			WHEN country_code = 'VA' THEN 'Holy See (Vatican City State)'
			WHEN country_code = 'VC' THEN 'Saint Vincent and the Grenadines'
			WHEN country_code = 'VE' THEN 'Venezuela'
			WHEN country_code = 'VG' THEN 'British Virgin Islands'
			WHEN country_code = 'VI' THEN 'U.S. Virgin Islands'
			WHEN country_code = 'VN' THEN 'Vietnam'
			WHEN country_code = 'VU' THEN 'Vanuatu'
			WHEN country_code = 'WF' THEN 'Wallis and Futuna'
			WHEN country_code = 'WS' THEN 'Samoa'
			WHEN country_code = 'XK' THEN 'Kosovo'
			WHEN country_code = 'XX' THEN 'Unknown'
			WHEN country_code = 'YE' THEN 'Yemen'
			WHEN country_code = 'YT' THEN 'Mayotte'
			WHEN country_code = 'ZA' THEN 'South Africa'
			WHEN country_code = 'ZM' THEN 'Zambia'
			WHEN country_code = 'ZW' THEN 'Zimbabwe'

			WHEN country_code = 'AC' THEN 'Anarcho-Capitalist'
			WHEN country_code = 'AN' THEN 'Anarchist'
			WHEN country_code = 'FC' THEN 'Fascist'
			WHEN country_code = 'JH' THEN 'Jihadi'
			WHEN country_code = 'KP' THEN 'North Korea'
			WHEN country_code = 'NB' THEN 'National Bolshevik'
			WHEN country_code = 'OB' THEN 'Obama'
			WHEN country_code = 'PC' THEN 'Hippie'
			WHEN country_code = 'RB' THEN 'Rebel'
			WHEN country_code = 'RP' THEN 'Libertarian'
			WHEN country_code = 'TM' THEN 'Templar'
			WHEN country_code = 'TP' THEN 'Tea Partier'
			WHEN country_code = 'TX' THEN 'Texan'
			WHEN country_code = 'UN' THEN 'United Nations'
			WHEN country_code = 'WP' THEN 'White Supremacist'

			ELSE country_name
		END 
		WHERE board = 'pol'
		AND timestamp >= 1497312000
		AND (country_name = '') IS NOT FALSE;
		"""

db.execute(query_update_country_names)
db.commit()


""" After 13 June 2017, both meme and troll flags were available.
However, some of the `country_codes` and `board_flag` codes can conflict.
Flags with potential conflicts:

<<<<<<< HEAD
=======
- BL: Black Nationalist / San Barthélemy
>>>>>>> 6aff55c1b7923d13386d245861459ff600f2f521
- CF: Confederate / Central African Republic
- CM: Communist / Cameroon
- GN: Gadsden / Guinea
- GY: Gay / Guyana
- KN: Kekistani / Saint Kitts and Nevis
- MF: Muslim / Saint Martin
- NZ: Nazi / New Zealand
- PR: Pirate / Puerto Rico
- RE: Republican / Réunion
- TM: Templar / Turkmenistan
- TR: Tree Hugger / Turkey
- BL: Black Nationalist / Saint Barthélemy
- DM: Democrat / Dominica

We use the 4plebs /pol/ dump to first fill in all the posts with troll country names with these codes.
"""

# Loop through the troll country data from the 4plebs dump
print("Updating ambiguous troll flags using the 4plebs dump.")
with open(PATH_TO_TROLL_FLAG_IDS, "r", encoding="utf-8") as in_json:

	troll_flags = json.load(in_json)

	# We don't want to intrepret country_names beyond the dump's latest post 
	max_id = int(max(list(troll_flags.keys())))
	min_id = int(min(list(troll_flags.keys())))

	troll_names = {
		"AC": "Anarcho-Capitalist",
		"AN": "Anarchist",
		"BL": "Black Nationalist",
		"CF": "Confederate",
		"CM": "Communist",
		"CT": "Catalonia",
		"DM": "Democrat"
		"GN": "Gadsden",
		"GY": "Gay",
		"JH": "Jihadi",
		"KN": "Kekistani",
		"MF": "Muslim",
		"NB": "National Bolshevik",
		"NZ": "Nazi",
		"PC": "Hippie",
		"PR": "Pirate",
		"RE": "Republican",
		"TM": "Templar",
		"TR": "Tree Hugger",
		"UN": "United Nations",
		"WP": "White Supremacist",
	}

	for troll_code, troll_name in troll_names.items():

		troll_ids = tuple([int(k) for k, v in troll_flags.items() if v == troll_code])

		query_update_ambiguous_troll_flag = ("""
			UPDATE posts_4chan
			SET country_name = '%s'
			WHERE id IN %s
			AND board = 'pol'
			AND (country_name = '') IS NOT FALSE;
		""" % (troll_name, troll_ids))

		db.execute(query_update_ambiguous_troll_flag)
		db.commit()

# For all the empty country_names in the timeframe of the dataset, we can assume they're an actual country
query_update_leftovers = ("""
		UPDATE posts_4chan
		SET country_name =
		CASE
			WHEN country_code = 'BL' THEN 'Saint Barthélemy'
			WHEN country_code = 'CM' THEN 'Cameroon'
			WHEN country_code = 'CF' THEN 'Central African Republic'
			WHEN country_code = 'DM' THEN 'Dominica'
			WHEN country_code = 'NZ' THEN 'New Zealand'
			WHEN country_code = 'KN' THEN 'Saint Kitts and Nevis'
			WHEN country_code = 'PR' THEN 'Puerto Rico'
			WHEN country_code = 'RE' THEN 'Réunion'
			WHEN country_code = 'MF' THEN 'Saint Martin'
			WHEN country_code = 'TR' THEN 'Turkey'
			WHEN country_code = 'TM' THEN 'Turkmenistan'
			WHEN country_code = 'GY' THEN 'Guyana'
			WHEN country_code = 'GN' THEN 'Guinea'
			WHEN country_code = 'BL' THEN 'Saint Barthélemy'
			ELSE ''
		END 
		WHERE board='pol'
		AND timestamp >= 1497312000
		AND id < %s
		AND id > %s
		AND (country_name = '') IS NOT FALSE;
		""" % (max_id, min_id))

db.execute(query_update_leftovers)
db.commit()

# Finally, we will prepend a `t_` to all troll flag country codes to avoid duplicates.
print("Prepending `t_` to the troll codes.")
query_update_troll_codes = """
		UPDATE posts_4chan
		SET country_code =
		CASE
			WHEN country_name = 'Anarchist' THEN 't_AN'
			WHEN country_name = 'Anarcho-Capitalist' THEN 't_AC'
			WHEN country_name = 'Black Nationalist' THEN 't_BL'
			WHEN country_name = 'Black Lives Matter' THEN 't_BL'
			WHEN country_name = 'Catalonia' THEN 't_CT'
			WHEN country_name = 'Commie' THEN 't_CM'
			WHEN country_name = 'Communist' THEN 't_CM'
			WHEN country_name = 'Confederate' THEN 't_CF'
			WHEN country_name = 'Democrat' THEN 't_DM'
			WHEN country_name = 'DEUS VULT' THEN 't_TM'
			WHEN country_name = 'European' THEN 't_EU'
			WHEN country_name = 'Europe' THEN 't_EU'
			WHEN country_name = 'Fascist' THEN 't_FC'
			WHEN country_name = 'Gadsden' THEN 't_GN'
			WHEN country_name = 'Gay' THEN 't_GY'
			WHEN country_name = 'LGBT' THEN 't_GY'
			WHEN country_name = 'Hippie' THEN 't_PC'
			WHEN country_name = 'Israel' THEN 'IL'
			WHEN country_name = 'Jihadi' THEN 't_JH'
			WHEN country_name = 'Kekistani' THEN 't_KN'
			WHEN country_name = 'Libertarian' THEN 't_RP'
			WHEN country_name = 'Muslim' THEN 't_MF'
			WHEN country_name = 'National Bolshevik' THEN 't_NB'
			WHEN country_name = 'Nazi' THEN 't_NZ'
			WHEN country_name = 'North Korea' THEN 'KP'
			WHEN country_name = 'Obama' THEN 't_OB'
			WHEN country_name = 'Pirate' THEN 't_PR'
			WHEN country_name = 'Rebel' THEN 't_RB'
			WHEN country_name = 'Republican' THEN 't_RE'
			WHEN country_name = 'Tea Partier' THEN 't_TP'
			WHEN country_name = 'Templar' THEN 't_TM'
			WHEN country_name = 'Texan' THEN 't_TX'
			WHEN country_name = 'Tree Hugger' THEN 't_TR'
			WHEN country_name = 'United Nations' THEN 't_UN'
			WHEN country_name = 'White Supremacist' THEN 't_WP'
			ELSE country_code
		END 
		WHERE board = 'pol' AND country_name IN ('Anarchist','Anarcho-Capitalist','Black Nationalist','Black Lives Matter','Catalonia','Commie','Communist','Confederate','Democrat', 'DEUS VULT','European','Europe','Fascist','Gadsden','Gay','LGBT','Hippie','Jihadi','Kekistani','Libertarian','Muslim','National Bolshevik','Nazi','Obama','Pirate','Rebel','Republican','Tea Partier','Templar','Texan','Tree Hugger','United Nations','White Supremacist');
		"""

db.execute(query_update_troll_codes)
db.commit()
print("Finished")