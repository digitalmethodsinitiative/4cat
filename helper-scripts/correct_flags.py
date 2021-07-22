"""

Script to set all the flags in the correct manner for a /pol/ dataset.

"""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")
from common.lib.database import Database
from common.lib.logger import Logger

PATH_TO_TROLL_FLAG_IDS = None

if not PATH_TO_TROLL_FLAG_IDS:
	print("You must provide a path to a json file with post ID: troll_code key/value pairs.")
	exit()
logger = Logger()
db = Database(logger=logger, appname="queue-dump")

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
			WHEN country_code = 'CF' THEN 'Conferedate'
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
			WHEN country_code = 'AD' THEN 'Andorra'
			WHEN country_code = 'AE' THEN 'United Arab Emirates'
			WHEN country_code = 'AF' THEN 'Afghanistan'
			WHEN country_code = 'AL' THEN 'Albania'
			WHEN country_code = 'AM' THEN 'Armenia'
			WHEN country_code = 'AO' THEN 'Angola'
			WHEN country_code = 'AR' THEN 'Argentina'
			WHEN country_code = 'AT' THEN 'Austria'
			WHEN country_code = 'AU' THEN 'Australia'
			WHEN country_code = 'AW' THEN 'Aruba'
			WHEN country_code = 'AX' THEN 'Aland'
			WHEN country_code = 'AZ' THEN 'Azerbaijan'
			WHEN country_code = 'BA' THEN 'Bosnia and Herzegovina'
			WHEN country_code = 'BB' THEN 'Barbados'
			WHEN country_code = 'BD' THEN 'Bangladesh'
			WHEN country_code = 'BE' THEN 'Belgium'
			WHEN country_code = 'BG' THEN 'Bulgaria'
			WHEN country_code = 'BM' THEN 'Bermuda'
			WHEN country_code = 'BO' THEN 'Bolivia'
			WHEN country_code = 'BR' THEN 'Brazil'
			WHEN country_code = 'BS' THEN 'Bahamas'
			WHEN country_code = 'BT' THEN 'Bhutan'
			WHEN country_code = 'BW' THEN 'Botswana'
			WHEN country_code = 'BY' THEN 'Belarus'
			WHEN country_code = 'BZ' THEN 'Belize'
			WHEN country_code = 'CA' THEN 'Canada'
			WHEN country_code = 'CH' THEN 'Switzerland'
			WHEN country_code = 'CL' THEN 'Chile'
			WHEN country_code = 'CM' THEN 'Cameroon'
			WHEN country_code = 'CN' THEN 'China'
			WHEN country_code = 'CO' THEN 'Colombia'
			WHEN country_code = 'CR' THEN 'Costa Rica'
			WHEN country_code = 'CU' THEN 'Cuba'
			WHEN country_code = 'CW' THEN 'Curaçao'
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
			WHEN country_code = 'ES' THEN 'Spain'
			WHEN country_code = 'ET' THEN 'Ethiopia'
			WHEN country_code = 'EU' THEN 'European'
			WHEN country_code = 'FI' THEN 'Finland'
			WHEN country_code = 'FJ' THEN 'Fiji Islands'
			WHEN country_code = 'FO' THEN 'Faroe Islands'
			WHEN country_code = 'FR' THEN 'France'
			WHEN country_code = 'GB' THEN 'United Kingdom'
			WHEN country_code = 'GE' THEN 'Georgia'
			WHEN country_code = 'GG' THEN 'Guernsey'
			WHEN country_code = 'GR' THEN 'Greece'
			WHEN country_code = 'GT' THEN 'Guatemala'
			WHEN country_code = 'GU' THEN 'Guam'
			WHEN country_code = 'HK' THEN 'Hong Kong'
			WHEN country_code = 'HN' THEN 'Honduras'
			WHEN country_code = 'HR' THEN 'Croatia'
			WHEN country_code = 'HU' THEN 'Hungary'
			WHEN country_code = 'ID' THEN 'Indonesia'
			WHEN country_code = 'IE' THEN 'Ireland'
			WHEN country_code = 'IL' THEN 'Israel'
			WHEN country_code = 'IM' THEN 'Isle of Man'
			WHEN country_code = 'IN' THEN 'India'
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
			WHEN country_code = 'KR' THEN 'South Korea'
			WHEN country_code = 'KW' THEN 'Kuwait'
			WHEN country_code = 'KY' THEN 'Cayman Islands'
			WHEN country_code = 'KZ' THEN 'Kazakhstan'
			WHEN country_code = 'LB' THEN 'Lebanon'
			WHEN country_code = 'LI' THEN 'Liechtenstein'
			WHEN country_code = 'LK' THEN 'Sri Lanka'
			WHEN country_code = 'LT' THEN 'Lithuania'
			WHEN country_code = 'LU' THEN 'Luxembourg'
			WHEN country_code = 'LV' THEN 'Latvia'
			WHEN country_code = 'LY' THEN 'Libya'
			WHEN country_code = 'MA' THEN 'Morocco'
			WHEN country_code = 'MC' THEN 'Monaco'
			WHEN country_code = 'MD' THEN 'Moldova'
			WHEN country_code = 'ME' THEN 'Montenegro'
			WHEN country_code = 'MK' THEN 'Macedonia'
			WHEN country_code = 'MM' THEN 'Myanmar'
			WHEN country_code = 'MN' THEN 'Mongolia'
			WHEN country_code = 'MO' THEN 'Macao'
			WHEN country_code = 'MR' THEN 'Mauritania'
			WHEN country_code = 'MT' THEN 'Malta'
			WHEN country_code = 'MU' THEN 'Mauritius'
			WHEN country_code = 'MW' THEN 'Malawi'
			WHEN country_code = 'MX' THEN 'Mexico'
			WHEN country_code = 'MY' THEN 'Malaysia'
			WHEN country_code = 'MZ' THEN 'Mozambique'
			WHEN country_code = 'NC' THEN 'New Caledonia'
			WHEN country_code = 'NG' THEN 'Nigeria'
			WHEN country_code = 'NL' THEN 'Netherlands'
			WHEN country_code = 'NO' THEN 'Norway'
			WHEN country_code = 'NP' THEN 'Nepal'
			WHEN country_code = 'NZ' THEN 'New Zealand'
			WHEN country_code = 'PA' THEN 'Panama'
			WHEN country_code = 'PE' THEN 'Peru'
			WHEN country_code = 'PH' THEN 'Philippines'
			WHEN country_code = 'PK' THEN 'Pakistan'
			WHEN country_code = 'PL' THEN 'Poland'
			WHEN country_code = 'PR' THEN 'Puerto Rico'
			WHEN country_code = 'PS' THEN 'Palestine'
			WHEN country_code = 'PT' THEN 'Portugal'
			WHEN country_code = 'PY' THEN 'Paraguay'
			WHEN country_code = 'QA' THEN 'Qatar'
			WHEN country_code = 'RE' THEN 'Réunion'
			WHEN country_code = 'RO' THEN 'Romania'
			WHEN country_code = 'RS' THEN 'Serbia'
			WHEN country_code = 'RU' THEN 'Russian Federation'
			WHEN country_code = 'SA' THEN 'Saudi Arabia'
			WHEN country_code = 'SC' THEN 'Seychelles'
			WHEN country_code = 'SE' THEN 'Sweden'
			WHEN country_code = 'SG' THEN 'Singapore'
			WHEN country_code = 'SI' THEN 'Slovenia'
			WHEN country_code = 'SK' THEN 'Slovakia'
			WHEN country_code = 'SV' THEN 'El Salvador'
			WHEN country_code = 'TH' THEN 'Thailand'
			WHEN country_code = 'TN' THEN 'Tunisia'
			WHEN country_code = 'TR' THEN 'Turkey'
			WHEN country_code = 'TT' THEN 'Trinidad and Tobago'
			WHEN country_code = 'TW' THEN 'Taiwan'
			WHEN country_code = 'TZ' THEN 'Tanzani'
			WHEN country_code = 'UA' THEN 'Ukraine'
			WHEN country_code = 'UG' THEN 'Uganda'
			WHEN country_code = 'US' THEN 'United States'
			WHEN country_code = 'UY' THEN 'Uruguay'
			WHEN country_code = 'VC' THEN 'Saint Vincent and the Grenadines'
			WHEN country_code = 'VE' THEN 'Venezuela'
			WHEN country_code = 'VI' THEN 'U.S. Virgin Islands'
			WHEN country_code = 'VN' THEN 'Vietnam'
			WHEN country_code = 'XX' THEN 'Unknown'
			WHEN country_code = 'ZA' THEN 'South Africa'
			ELSE ''
		END 
		WHERE board='pol'
		AND timestamp >= 1418515200 AND timestamp < 1497312000
		AND (country_name = '') IS NOT FALSE;
		"""

db.execute(query_update_country_flags)
db.commit()

""" After 13 June 2017, both meme and troll flags were available.
However, some of the `country_codes` and `board_flag` codes can conflict.
Flags with potential conflicts:

- CM: Communist / Cameroon
- NZ: Nazi / New Zealand
- PR: Pirate / Puerto Rico
- RE: Republican / Réunion
- TR: Tree Hugger / Turkey

"""

print("Settings `country_names` for posts after 13 June 2017.")

query_update_country_names = """
		UPDATE posts_4chan
		SET country_name =
		CASE
			WHEN country_code = 'AD' THEN 'Andorra'
			WHEN country_code = 'AE' THEN 'United Arab Emirates'
			WHEN country_code = 'AF' THEN 'Afghanistan'
			WHEN country_code = 'AL' THEN 'Albania'
			WHEN country_code = 'AM' THEN 'Armenia'
			WHEN country_code = 'AO' THEN 'Angola'
			WHEN country_code = 'AR' THEN 'Argentina'
			WHEN country_code = 'AT' THEN 'Austria'
			WHEN country_code = 'AU' THEN 'Australia'
			WHEN country_code = 'AW' THEN 'Aruba'
			WHEN country_code = 'AX' THEN 'Aland'
			WHEN country_code = 'AZ' THEN 'Azerbaijan'
			WHEN country_code = 'BA' THEN 'Bosnia and Herzegovina'
			WHEN country_code = 'BB' THEN 'Barbados'
			WHEN country_code = 'BD' THEN 'Bangladesh'
			WHEN country_code = 'BE' THEN 'Belgium'
			WHEN country_code = 'BG' THEN 'Bulgaria'
			WHEN country_code = 'BM' THEN 'Bermuda'
			WHEN country_code = 'BO' THEN 'Bolivia'
			WHEN country_code = 'BR' THEN 'Brazil'
			WHEN country_code = 'BS' THEN 'Bahamas'
			WHEN country_code = 'BT' THEN 'Bhutan'
			WHEN country_code = 'BW' THEN 'Botswana'
			WHEN country_code = 'BY' THEN 'Belarus'
			WHEN country_code = 'BZ' THEN 'Belize'
			WHEN country_code = 'CA' THEN 'Canada'
			WHEN country_code = 'CH' THEN 'Switzerland'
			WHEN country_code = 'CL' THEN 'Chile'
			WHEN country_code = 'CN' THEN 'China'
			WHEN country_code = 'CO' THEN 'Colombia'
			WHEN country_code = 'CR' THEN 'Costa Rica'
			WHEN country_code = 'CU' THEN 'Cuba'
			WHEN country_code = 'CW' THEN 'Curaçao'
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
			WHEN country_code = 'ES' THEN 'Spain'
			WHEN country_code = 'ET' THEN 'Ethiopia'
			WHEN country_code = 'EU' THEN 'European'
			WHEN country_code = 'FI' THEN 'Finland'
			WHEN country_code = 'FJ' THEN 'Fiji Islands'
			WHEN country_code = 'FO' THEN 'Faroe Islands'
			WHEN country_code = 'FR' THEN 'France'
			WHEN country_code = 'GB' THEN 'United Kingdom'
			WHEN country_code = 'GE' THEN 'Georgia'
			WHEN country_code = 'GG' THEN 'Guernsey'
			WHEN country_code = 'GR' THEN 'Greece'
			WHEN country_code = 'GT' THEN 'Guatemala'
			WHEN country_code = 'GU' THEN 'Guam'
			WHEN country_code = 'HK' THEN 'Hong Kong'
			WHEN country_code = 'HN' THEN 'Honduras'
			WHEN country_code = 'HR' THEN 'Croatia'
			WHEN country_code = 'HU' THEN 'Hungary'
			WHEN country_code = 'ID' THEN 'Indonesia'
			WHEN country_code = 'IE' THEN 'Ireland'
			WHEN country_code = 'IL' THEN 'Israel'
			WHEN country_code = 'IM' THEN 'Isle of Man'
			WHEN country_code = 'IN' THEN 'India'
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
			WHEN country_code = 'KR' THEN 'South Korea'
			WHEN country_code = 'KW' THEN 'Kuwait'
			WHEN country_code = 'KY' THEN 'Cayman Islands'
			WHEN country_code = 'KZ' THEN 'Kazakhstan'
			WHEN country_code = 'LB' THEN 'Lebanon'
			WHEN country_code = 'LI' THEN 'Liechtenstein'
			WHEN country_code = 'LK' THEN 'Sri Lanka'
			WHEN country_code = 'LT' THEN 'Lithuania'
			WHEN country_code = 'LU' THEN 'Luxembourg'
			WHEN country_code = 'LV' THEN 'Latvia'
			WHEN country_code = 'LY' THEN 'Libya'
			WHEN country_code = 'MA' THEN 'Morocco'
			WHEN country_code = 'MC' THEN 'Monaco'
			WHEN country_code = 'MD' THEN 'Moldova'
			WHEN country_code = 'ME' THEN 'Montenegro'
			WHEN country_code = 'MK' THEN 'Macedonia'
			WHEN country_code = 'MM' THEN 'Myanmar'
			WHEN country_code = 'MN' THEN 'Mongolia'
			WHEN country_code = 'MO' THEN 'Macao'
			WHEN country_code = 'MR' THEN 'Mauritania'
			WHEN country_code = 'MT' THEN 'Malta'
			WHEN country_code = 'MU' THEN 'Mauritius'
			WHEN country_code = 'MW' THEN 'Malawi'
			WHEN country_code = 'MX' THEN 'Mexico'
			WHEN country_code = 'MY' THEN 'Malaysia'
			WHEN country_code = 'MZ' THEN 'Mozambique'
			WHEN country_code = 'NC' THEN 'New Caledonia'
			WHEN country_code = 'NG' THEN 'Nigeria'
			WHEN country_code = 'NL' THEN 'Netherlands'
			WHEN country_code = 'NO' THEN 'Norway'
			WHEN country_code = 'NP' THEN 'Nepal'
			WHEN country_code = 'PA' THEN 'Panama'
			WHEN country_code = 'PE' THEN 'Peru'
			WHEN country_code = 'PH' THEN 'Philippines'
			WHEN country_code = 'PK' THEN 'Pakistan'
			WHEN country_code = 'PL' THEN 'Poland'
			WHEN country_code = 'PS' THEN 'Palestine'
			WHEN country_code = 'PT' THEN 'Portugal'
			WHEN country_code = 'PY' THEN 'Paraguay'
			WHEN country_code = 'QA' THEN 'Qatar'
			WHEN country_code = 'RO' THEN 'Romania'
			WHEN country_code = 'RS' THEN 'Serbia'
			WHEN country_code = 'RU' THEN 'Russian Federation'
			WHEN country_code = 'SA' THEN 'Saudi Arabia'
			WHEN country_code = 'SC' THEN 'Seychelles'
			WHEN country_code = 'SE' THEN 'Sweden'
			WHEN country_code = 'SG' THEN 'Singapore'
			WHEN country_code = 'SI' THEN 'Slovenia'
			WHEN country_code = 'SK' THEN 'Slovakia'
			WHEN country_code = 'SV' THEN 'El Salvador'
			WHEN country_code = 'TH' THEN 'Thailand'
			WHEN country_code = 'TN' THEN 'Tunisia'
			WHEN country_code = 'TT' THEN 'Trinidad and Tobago'
			WHEN country_code = 'TW' THEN 'Taiwan'
			WHEN country_code = 'TZ' THEN 'Tanzani'
			WHEN country_code = 'UA' THEN 'Ukraine'
			WHEN country_code = 'UG' THEN 'Uganda'
			WHEN country_code = 'US' THEN 'United States'
			WHEN country_code = 'UY' THEN 'Uruguay'
			WHEN country_code = 'VC' THEN 'Saint Vincent and the Grenadines'
			WHEN country_code = 'VE' THEN 'Venezuela'
			WHEN country_code = 'VI' THEN 'U.S. Virgin Islands'
			WHEN country_code = 'VN' THEN 'Vietnam'
			WHEN country_code = 'XX' THEN 'Unknown'
			WHEN country_code = 'ZA' THEN 'South Africa'
			WHEN country_code = 'AC' THEN 'Anarcho-Capitalist'
			WHEN country_code = 'AN' THEN 'Anarchist'
			WHEN country_code = 'BL' THEN 'Black Nationalist'
			WHEN country_code = 'CF' THEN 'Conferedate'
			WHEN country_code = 'DM' THEN 'Democrat'
			WHEN country_code = 'GN' THEN 'Gadsden'
			WHEN country_code = 'GY' THEN 'Gay'
			WHEN country_code = 'JH' THEN 'Jihadi'
			WHEN country_code = 'KN' THEN 'Kekistani'
			WHEN country_code = 'KP' THEN 'North Korea'
			WHEN country_code = 'MF' THEN 'Muslim'
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
			ELSE ''
		END 
		WHERE board='pol'
		AND timestamp >= 1497312000
		AND (country_name = '') IS NOT FALSE;
		"""

db.execute(query_update_country_names)
db.commit()


""" After 13 June 2017, both meme and troll flags were available.
However, some of the `country_codes` and `board_flag` codes can conflict.
Flags with potential conflicts:

- CM: Communist / Cameroon
- NZ: Nazi / New Zealand
- PR: Pirate / Puerto Rico
- RE: Republican / Réunion
- TR: Tree Hugger / Turkey

"""

# Loop through the troll country data from the 4plebs dump
print("Updating ambiguous troll flags using the 4plebs dump.")
with open(PATH_TO_TROLL_FLAG_IDS, "r", encoding="utf-8") as in_json:

	troll_flags = json.load(in_json)

	troll_names = {
		"CM": "Communist",
		"NZ": "Nazi",
		"PR": "Pirate",
		"RE": "Republican",
		"TR": "Tree Hugger"
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

# For all the empty country_names, we can assume they're a country name
query_update_leftovers = """
		UPDATE posts_4chan
		SET country_name =
		CASE
			WHEN country_code = 'CM' THEN 'Cameroon'
			WHEN country_code = 'NZ' THEN 'New Zealand'
			WHEN country_code = 'PR' THEN 'Puerto Rico'
			WHEN country_code = 'RE' THEN 'Réunion'
			WHEN country_code = 'TR' THEN 'Turkey'
			ELSE ''
		END 
		WHERE board='pol'
		AND timestamp >= 1497312000
		AND (country_name = '') IS NOT FALSE;
		"""

db.execute(query_update_leftovers)
db.commit()

# Finally, we will prepend a `t_` to all troll flag country codes to avoid duplicates.
print("Prepending `t_` to the troll codes.")
query_update_troll_codes = """
		UPDATE posts_4chan
		SET country_code =
		CASE
			WHEN country_name = "Anarchist" THEN 't_AN'
			WHEN country_name = "Anarcho-Capitalist" THEN 't_AC'
			WHEN country_name = "Black Nationalist" THEN 't_BL'
			WHEN country_name = "Black Lives Matter" THEN 't_BL'
			WHEN country_name = "Commie" THEN 't_CM'
			WHEN country_name = "Communist" THEN 't_CM'
			WHEN country_name = "Conferedate" THEN 't_CF'
			WHEN country_name = "Democrat" THEN 't_DM'
			WHEN country_name = "European" THEN 't_EU'
			WHEN country_name = "Europe" THEN 't_EU'
			WHEN country_name = "Gadsden" THEN 't_GN'
			WHEN country_name = "Gay" THEN 't_GY'
			WHEN country_name = "LGBT" THEN 't_GY'
			WHEN country_name = "Hippie" THEN 't_PC'
			WHEN country_name = "Israel" THEN 'IL' # Israel is an actual country name
			WHEN country_name = "Jihadi" THEN 't_JH'
			WHEN country_name = "Kekistani" THEN 't_KN'
			WHEN country_name = "Libertarian" THEN 't_RP'
			WHEN country_name = "Muslim" THEN 't_MF'
			WHEN country_name = "National Bolshevik" THEN 't_NB'
			WHEN country_name = "Nazi" THEN 't_NZ'
			WHEN country_name = "North Korea" THEN 't_KP'
			WHEN country_name = "Obama" THEN 't_OB'
			WHEN country_name = "Pirate" THEN 't_PR'
			WHEN country_name = "Rebel" THEN 't_RB'
			WHEN country_name = "Republican" THEN 't_RE'
			WHEN country_name = "Tea Partier" THEN 't_TP'
			WHEN country_name = "Templar" THEN 't_TM'
			WHEN country_name = "Texan" THEN 't_TX'
			WHEN country_name = "Tree Hugger" THEN 't_TR'
			WHEN country_name = "United Nations" THEN 't_UN'
			WHEN country_name = "White Supremacist" THEN 't_WP'
			ELSE ''
		END 
		WHERE board = 'pol';
		"""

db.execute(query_update_leftovers)
db.commit()
print("Finished")