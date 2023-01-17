# DMI-TCAT data source for 4CAT

This datasource interfaces with a query bin in [DMI-TCAT](https://github.com/digitalmethodsinitiative/dmi-tcat) to
create datasets of tweets collected by that tool. DMI-TCAT scrapes tweets as they are created and stores them in 'bins'
of tweets matching a certain query. With this data source, 4CAT can be used to create datasets from tweets in a bin,
and process them in the usual ways.

dmi-tcatv2 interfaces directly with a TCAT database allowing users to perform any desired query to create new 4CAT
datasets.

## Basic query
Allows users to query specific bins by data as well as text matches
It is equivalent to the following:
`SELECT * FROM %s_tweets WHERE lower(text) LIKE %s ` % (bin_name, your_text_query)
Basic query also allows AND and OR statements for text.

## Advanced query
The advanced query will send any query you desire to the TCAT database. Knowledge of the database structure helps,
but you can also send simple queries such as `SHOW TABLES`.
*WARNING* You should create a view only TCAT database user otherwise a malicious user could harm your database!

# How to enable
## Create a new database MySQL user with proper credentials
### Allow TCAT MySQL database to be accessed remotely
Your TCAT database likely needs to be accessed remotely; you can skip this if 4CAT and TCAT are on the same
machine/server (https://mariadb.com/kb/en/configuring-mariadb-for-remote-client-access/)
1. Comment out `skip-networking` (if active) and `bind-address` in your mysql configuation. `/etc/mysql/mariadb.conf.d/` should contain the `.cnf` files to be edited.
`bind-address` is most likely located in `/etc/mysql/mariadb.conf.d/50-server.cnf`.
2. Restart mysql `sudo systemctl restart mariadb.service`

# Add a new user with only SELECT access to the database
1. Add a new user to access remotely by login into your TCAT database (via `mysql -D twittercapture -u tcatdbuser -p`) and run the following
`GRANT SELECT ON twittercapture.* TO newuser@'1.2.3.4' IDENTIFIED BY 'newpassword';` where `newuser` is the name of the new user, `newpassword`
is their password and `1.2.3.4` is the IP address from which 4CAT will access the database
- wildcards are allowed in IP addresses, so in principle something like 192.168.% could give access across a local network.

## Add the database and user information to 4CAT settings
Under the 4CAT Settings tab, look for the "DMI-TCAT Search (MySQL)" settings where the instances to connect to can be configured.