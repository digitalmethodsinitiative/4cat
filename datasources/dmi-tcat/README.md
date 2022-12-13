# DMI-TCAT data source for 4CAT

This datasource interfaces with a query bin in [DMI-TCAT](https://github.com/digitalmethodsinitiative/dmi-tcat) to
create datasets of tweets collected by that tool. DMI-TCAT scrapes tweets as they are created and stores them in 'bins'
of tweets matching a certain query. With this data source, 4CAT can be used to create datasets from tweets in a bin,
and process them in the usual ways.

dmi-tcat interfaces directly with the TCAT frontend and allowing users to access the
`/analysis/mod.export_tweets.php` endpoint to request TCAT tweets.

# How to enable
Under the 4CAT Settings tab, look for the "DMI-TCAT Search (HTTP)" settings where the instances to connect to can be configured.
