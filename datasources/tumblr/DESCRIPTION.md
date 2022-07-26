The Tumblr data is retrieved by interfacing with the [Tumblr API](https://api.tumblr.com).
It is only possible to get posts by tag or per blog, since the API does not allow keyword search.

### Privacy
Be aware that the data may contain personal information. It is thus recommended to pseudonymise the data.

To comply with the Tumblr API requirements, Tumblr datasets are deleted after three days. 

### Rate limits
4CAT uses an internal API key to get Tumblr posts. These are limited to the
[following rate limits](https://www.tumblr.com/docs/en/api/v2#rate-limits). However, administrators
may request a rate limit increase via Tumblr.

### Date bugs
The [Tumblr API](https://api.tumblr.com) is volatile: when fetching sporadically used 
tags, it may return zero posts, even though older posts *do* exist. Check the oldest post in 
your dataset to see if it this is indeed the case and whether any odd time gaps exists.
4CAT tries to mitigate this by decreasing the date parameter (<code>before</code>) with
six hours and sending the query again. This often successfully returns older, un-fetched posts.
If it didn't find new data after checking 24 days in the past, it checks for data up to six years
before the last checked date (decreasing 12 times by 6 months). If that also results in nothing,
it assumes the dataset is complete.