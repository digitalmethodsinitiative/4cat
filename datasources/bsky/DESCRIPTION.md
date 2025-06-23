The Bluesky data source searches for posts and collects them based on your queries. You can optionally only collect 
posts within a given date range. You can only select a certain amount of posts per query (this is a limitation set
by your 4CAT administrators per usertype).

### Search queries
Bluesky has tips and tricks to using their search engine, which you can find [here](https://bsky.social/about/blog/05-31-2024-search).

4CAT uses the Bluesky API via `atproto` to collect posts which requires a user to be logged in. It is therefore possible
that your search results are tailored to your user profile. You may therefore wish to create a new user profile for your
research.

You can currently search by the following:

- Keywords (use quotes for exact matches)
- From or mentioning a user
  - Use `from:username` to search for posts from a user
  - Use `to:username` or `mentions:username` to search for posts mentioning a user
  - Use `"@username"` to search for posts including the text "@username" whether they were tagged or not
- URL
  - Use `domain:example.com` to search for posts with the domain "example.com".
- Language
  - Use `lang:en` to search for posts in English for example.
- Date range is best set in the 4CAT interface, but can also be set per query using `since:YYYY-MM-DD` and `until:YYYY-MM-DD`.

Note: commas (`,`) are used by 4CAT to separate queries, so you should not use them in your queries. If you have such a
requirement, please contact your 4CAT administrator.

### Technical details and caveats
Bluesky data is collected via Bluesky's [official API](https://docs.bsky.app/docs/get-started) via the
[AT Protocol](https://atproto.blue/en/latest/). This is done using the [AT Protocol library](https://pypi.org/project/atproto/) 
for Python. You can always view the latest code used by 4CAT to collect Bluesky data [here](https://github.com/digitalmethodsinitiative/4cat/blob/master/datasources/bsky/search_bsky.py);
each dataset contains a unique `commit` identifier which you can use to find the exact code used to collect your data.

### Data format
Posts are saved as JSON objects, combined in one [NDJSON](http://ndjson.org/) file. For each post, the object 
collected with `atproto` is mapped to JSON. A lot of information is included per post, more than can be explained 
here. You can read more about the post data structure here in [this 
documentation](https://docs.bsky.app/docs/advanced-guides/posts). Most 
metadata you may be interested in is included or can be derived from the included data.

NDJSON files can also be downloaded as a CSV file in 4CAT. In this case, only the most important attributes
of a post (such as text body, timestamp, author name, and whether it was forwarded) are included in the CSV file.
The CSV structure will appear the same as in the Preview view in 4CAT.

#### Note on User handles and post URLs
 In Bluesky, user handles can change. They are also used in forming the URL of a post. It is thus
possible for a post's user handle and URL to change over time. Both the post and the user have unique IDs which will not
change and can be used to identify them and look up the new post URL or user handle.

In addition to the post, 4CAT therefore also collects the user handles of mentions, replies, quoted posts, etc. during
the collection process and uses these handles to create the URLs seen in the 4CAT preview and CSV export. If a handle 
cannot be looked up (e.g., the user has deleted their account, blocked certain users, was suspended), 4CAT will use the
author ID in place of the user handle. The raw data is stored in the JSON file as it is received from Bluesky and can 
be thus used to update the handles/URLs in the future if needed.
