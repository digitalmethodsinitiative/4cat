Twitter data is gathered through the official [Twitter v2 API](https://developer.twitter.com/en/docs/twitter-api). 4CAT
allows access to both the Standard and the Academic track. The Standard track is free for anyone to use, but only
allows to retrieve tweets up to seven days old. The Academic track allows a full-archive search of up to ten million
tweets per month (as of March 2022). For the Academic track, you need a valid Bearer token. You can request one
[here](https://developer.twitter.com/en/portal/petition/academic/is-it-right-for-you).

Tweets are captured in batches at a speed of approximately 100,000 tweets per hour. 4CAT will warn you if your dataset
is expected to take more than 30 minutes to collect. It is often a good idea to start small (with very specific
queries or narrow date ranges) and then only create a larger dataset if you are confident that it will be manageable and
useful for your analysis.

If you hit your Twitter API quota while creating a dataset, the dataset will be finished with the tweets that have been
collected so far and a warning will be logged.

### Query syntax

Check the [API documentation](https://developer.twitter.com/en/docs/twitter-api/tweets/search/integrate/build-a-query)
for available query syntax and operators. This information is crucial to what data you collect. Important operators for
instance include `-is:nullcast` and `-is:retweet`, with which you can ignore promoted tweets and retweets. Query syntax
is roughly the same as for Twitter's search interface, so you can try out most queries by entering them in the Twitter
app or website's search field and looking at the results. You can also test queries with
Twitter's [Query Builder](https://developer.twitter.com/apitools/query?query=).

### Date ranges

By default, Twitter returns tweets posted within the past 30 days. If you want to go back further, you need to
explicitly set a date range. Note that Twitter does not like date ranges that end in the future, or start before
Twitter existed. If you want to capture tweets "until now", it is often best to use yesterday as an end date.

### Geo parameters

Twitter offers a number of ways
to [query by location/geo data](https://developer.twitter.com/en/docs/tutorials/filtering-tweets-by-location)
such as `has:geo`, `place:Amsterdam`, or `place:Amsterdam`. This feature is only available for the Academic level;
you will receive a 400 error if using queries filtering by geographic information.

### Retweets

A retweet from Twitter API v2 contains at maximum 140 characters from the original tweet. 4CAT therefore
gathers both the retweet and the original tweet and reformats the retweet text so it resembles a user's experience.

This also affects mentions, hashtags, and other data as only those contained in the first 140 characters are provided
by Twitter API v2 with the retweet. Additional hashtags, mentions, etc. are taken from the original tweet and added
to the retweet for 4CAT analysis methods. *4CAT stores the data from Twitter API v2 as similar as possible to the format
in which it was received which you can obtain by downloading the ndjson file.*

*Example 1*

[This retweet](https://twitter.com/tonino1630/status/1554618034299568128) returns the following data:

- *author:*    `tonino1630`
- *
  text:*     `RT @ChuckyFrao: ¡HUELE A LIBERTAD! La Casa Blanca publicó una orden ejecutiva sobre las acciones del Gobierno de Joe Biden para negociar p…`
- *mentions:*     `ChuckyFrao`
- *hashags:*

<br>
While the original tweet will return (as a reference tweet) this data:

- *author:*    `ChuckyFrao`
- *
  text:*     `¡HUELE A LIBERTAD! La Casa Blanca publicó una orden ejecutiva sobre las acciones del Gobierno de Joe Biden para negociar presos estadounidenses en otros países. #FreeAlexSaab @POTUS @usembassyve @StateSPEHA @StateDept @SecBlinken #BringAlexHome #IntegridadTerritorial https://t.co/ClSQ3Rfax0`
- *mentions:*    `POTUS, usembassyve, StateSPEHA, StateDept, SecBlinken`
- *hashtags:*    `FreeAlexSaab, BringAlexHome, IntegridadTerritorial`

<br>
As you can see, only the author of the original tweet is listed as a mention in the retweet.

*Example 2*

[This retweet](https://twitter.com/Macsmart31/status/1554618041459445760) returns the following:

- *author:* `Macsmart31`
- *
  text:* `RT @mickyd123us: @tribelaw @HonorDecency Thank goodness Biden replaced his detail - we know that Pence refused to "Take A Ride" with the de…`
- *mentions:* `mickyd123us, tribelaw, HonorDecency`

<br>
Compared with the original tweet referenced below:

- *author:* `mickyd123us`
- *
  text:* `@tribelaw @HonorDecency Thank goodness Biden replaced his detail - we know that Pence refused to "Take A Ride" with the detail he had in the basement. Who knows where they would have taken him. https://t.co/s47Kb5RrCr`
- *mentions:* `tribelaw, HonorDecency`

<br>
Because the mentioned users are in the first 140 characters of the original tweet, they are also listed as mentions in the retweet.

The key difference here is that example one the retweet contains none of the hashtags or mentions from the original
tweet (they are beyond the first 140 characters) while the second retweet example does return mentions from the original
tweet. *Due to this discrepancy, for retweets all mentions and hashtags of the original tweet are considered as mentions
and hashtags of the retweet.* A user on Twitter will see all mentions and hashtags when viewing a retweet and the
retweet would be a part of any network around those mentions and hashtags.
