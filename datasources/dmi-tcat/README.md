# DMI-TCAT data source for 4CAT

This datasource interfaces with a query bin in [DMI-TCAT](https://github.com/digitalmethodsinitiative/dmi-tcat) to
create datasets of tweets collected by that tool. DMI-TCAT scrapes tweets as they are created and stores them in 'bins'
of tweets matching a certain query. With this data source, 4CAT can be used to create datasets from tweets in a bin,
and process them in the usual ways.