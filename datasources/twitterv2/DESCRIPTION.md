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

### Retweets
In addition to requesting the original tweet from Twitter API v2, 4CAT also requests referenced tweets. In some
instances this is necessary to get a full picture of what a user experiences. For example, the a retweet will only
contain at maximum 140 characters that reference the original tweet. 4CAT gathers both and reformats the retweet so
it contains the full text (e.g. "RT @SomeUser: BREAKING: This is the original tweet that is longer than 140
characters..." is formatted to "RT @SomeUser: BREAKING: This is the original tweet that is longer than 140
characters and includes text not available in the returned retweet").

Tweets can be retweets, replies, quotes, and combinations of these (as a user can retweet a quote, quote a tweet
they are replying to, et cetera). This affects mentions, hashtags, and other data as it can become difficult to
parse whether a user is directly mentioning another user or is quoting/retweeting that user.

For example, [this retweet](https://twitter.com/tonino1630/status/1554618034299568128) returns the following data.
```
author: "tonino1630"
text: "RT @ChuckyFrao: ¡HUELE A LIBERTAD! La Casa Blanca publicó una orden ejecutiva sobre las acciones del Gobierno
 de Joe Biden para negociar p…"
mentions: 'ChuckyFrao'
hashags:
```
While the original tweet will return (as a reference tweet) this data.
```
author: "ChuckyFrao"
text: "¡HUELE A LIBERTAD! La Casa Blanca publicó una orden ejecutiva sobre las acciones del Gobierno de Joe Biden para
negociar presos estadounidenses en otros países. #FreeAlexSaab @POTUS @usembassyve @StateSPEHA @StateDept @SecBlinken
#BringAlexHome #IntegridadTerritorial https://t.co/ClSQ3Rfax0"
mentions: 'POTUS', 'usembassyve', 'StateSPEHA', 'StateDept', 'SecBlinken'
hashtags: 'FreeAlexSaab', 'BringAlexHome', 'IntegridadTerritorial'
```
As you can see, only the author of the original tweet is listed as a mention in the retweet. However, [this retweet](https://twitter.com/Macsmart31/status/1554618041459445760)
returns the following.
```
author: "Macsmart31"
text: "RT @mickyd123us: @tribelaw @HonorDecency Thank goodness Biden replaced his detail - we know that Pence refused to
"Take A Ride" with the de…"
mentions: 'mickyd123us', 'tribelaw', 'HonorDecency'
```
Compared with the original tweet referenced below.
```
author: "mickyd123us"
text: "@tribelaw @HonorDecency Thank goodness Biden replaced his detail - we know that Pence refused to "Take A Ride" with
the detail he had in the basement.  Who knows where they would have taken him. https://t.co/s47Kb5RrCr"
mentions: 'tribelaw', 'HonorDecency'
```
Because the mentioned users are in the first 140 characters of the original tweet, they are also listed as mentions in
the retweet.

*Due to this discrepancy, for retweets all mentions and hashtags of the original tweet are considered as mentions and hashtags*
*of the retweet.* A user on Twitter will after all see all mentions and hashtags when viewing a retweet.
