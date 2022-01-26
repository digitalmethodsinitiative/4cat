# Twitter Full-Archive Search

This datasource interfaces with the 'Full-Archive Search' 
[endpoint](https://developer.twitter.com/en/docs/twitter-api/tweets/search/quick-start/full-archive-search)
of the Twitte API (v2) to allow historical searches of Twitter.

Access to this endpoint is only available by request for qualifying academic projects. To this end, users need to 
supply a 'bearer token' unique to their account to use the data source. There is additionally a usage cap of ten
million tweets per month per bearer token.

In contrast to many other sources, retrieved tweets are saved as an NDJSON file, instead of CSV. The Twitter API 
returns tweet data as a nested object, and this is not easily 'flattened' to a CSV file. To avoid throwing away
potentially valuable data, the full JSON object is stored. Processors can be used to generate a CSV file based on the
NDJSON file if this is desired for manual analysis.
