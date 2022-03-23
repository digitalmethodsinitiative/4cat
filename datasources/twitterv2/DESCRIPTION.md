Twitter data is gathered through the official [Twitter v2 API](https://developer.twitter.com/en/docs/twitter-api). 4CAT allows access to both the Standard and the Academic track. The Standard track is free for anyone to use, but only allows to retrieve tweets up to seven days old. The Academic track allows a full-archive search up to eighty million tweets per month (as of March 2022). For the Academic track, you need a valid Bearer token. You can request one [here](https://developer.twitter.com/en/portal/petition/academic/is-it-right-for-you).

### Query syntax
Check the [API documentation](https://developer.twitter.com/en/docs/twitter-api/tweets/search/integrate/build-a-query) for available query syntax and operators. This information is crucial to what data you collect. Important operators for instance include `-is:nullcast` and `-is:retweet`, with which you can ignore promoted tweets and retweets.

### Date operators
By default, Twitter returns tweets up til 30 days ago. If you want to go back further, you need to explicitly set a date range.