Twitter data is gathered through the official [Twitter v2 API](https://developer.twitter.com/en/docs/twitter-api). 4CAT 
allows access to both the Standard and the Academic track. The Standard track is free for anyone to use, but only 
allows to retrieve tweets up to seven days old. The Academic track allows a full-archive search of up to ten million 
tweets per month (as of March 2022). For the Academic track, you need a valid Bearer token. You can request one 
[here](https://developer.twitter.com/en/portal/petition/academic/is-it-right-for-you).

Tweets are captured in batches at a speed of approximately 100,000 tweets per hour. 4CAT will warn you if your dataset
is expected to take more than 30 minutes to collect. It is often a good idea to start small (with very specific 
queries or narrow date ranges) and then only create a larger dataset if you are confident that it will be manageable and
useful for your analysis.

### Query syntax
Check the [API documentation](https://developer.twitter.com/en/docs/twitter-api/tweets/search/integrate/build-a-query) 
for available query syntax and operators. This information is crucial to what data you collect. Important operators for 
instance include `-is:nullcast` and `-is:retweet`, with which you can ignore promoted tweets and retweets. Query syntax
is roughly the same as for Twitter's search interface, so you can try out most queries by entering them in the Twitter
app or website's search field and looking at the results.

### Date ranges
By default, Twitter returns tweets posted within the past 30 days. If you want to go back further, you need to 
explicitly set a date range. Note that Twitter does not like date ranges that end in the future, or start before 
Twitter existed. If you want to capture tweets "until now", it is often best to use yesterday as an end date.