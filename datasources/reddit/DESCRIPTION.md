Reddit data is retrieved from [Pushshift](https://pushshift.io). Check the [Pushshift API reference](https://pushshift.io/api-parameters/) for documentation on syntax, e.g. on how to format keyword queries.

You can check your syntax by querying the API directly, e.g. through the URL [https://api.pushshift.io/reddit/search/comment/?subreddit=babyelephantgifs&q=dumbo](https://api.pushshift.io/reddit/search/comment/?subreddit=babyelephantgifs&q=dumbo).

At the moment 4CAT only allows querying based on keyword search. You can find recent data dumps [here.](https://files.pushshift.io/reddit/)

We offer access to the <code>regular</code> Pushshift endpoint and the new <code>beta</code> endpoint. The former is more stable, but the latter is faster. The documentation for the beta version can be found [here](https://beta.pushshift.io/redoc).

### Missing data
It is common for the Pushshift data to feature gaps. This may be caused by a delay in scraping or because its developers have to carry out maintenance. Always check the completeness of your data.

The data might be incomplete on either endpoint. According to the Pushshift developers, the beta endpoint should be complete soon. You can check the [r/pushshift subreddit](https://reddit.com/r/pushshift) to check if there's any updates or outages. 