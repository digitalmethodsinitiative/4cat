X/Twitter data is gathered through the official [X v2 API](https://developer.twitter.com/en/docs/twitter-api). 4CAT can interface with X's Research API (sometimes 
branded as the 'DSA API', referencing the EU's Digital Services Act). To retrieve posts via this API with 4CAT, you need
a valid Bearer token. Read more about this mode of access [here](https://developer.x.com/en/use-cases/do-research/academic-research).

Posts are captured in batches at a speed of approximately 100,000 posts per hour. 4CAT will warn you if your dataset
is expected to take more than 30 minutes to collect. It is often a good idea to start small (with very specific
queries or narrow date ranges) and then only create a larger dataset if you are confident that it will be manageable and
useful for your analysis.

If you hit your X API quota while creating a dataset, the dataset will be finished with the posts that have been 
collected so far and a warning will be logged.

### Query syntax

Check the [API documentation](https://developer.x.com/en/docs/x-api/tweets/search/integrate/build-a-query)
for available query syntax and operators. This information is crucial to what data you collect. Important operators for
instance include `-is:nullcast` and `-is:retweet`, with which you can ignore promoted posts and reposts. Query syntax
is roughly the same as for X's search interface, so you can try out most queries by entering them in the X app or 
website's search field and looking at the results. You can also test queries with
X's [Query Builder](https://developer.twitter.com/apitools/query?query=).

### Date ranges

By default, X returns posts posted within the past 30 days. If you want to go back further, you need to
explicitly set a date range. Note that X does not like date ranges that end in the future, or start before
Twitter existed. If you want to capture tweets "until now", it is often best to use yesterday as an end date. Also note
that API access may come with certain limitations on how far a query may extend into history.

### Geo parameters

X offers a number of ways
to [query by location/geo data](https://developer.x.com/en/docs/tutorials/filtering-tweets-by-location)
such as `has:geo`, `place:Amsterdam`, or `place:Amsterdam`. 

### Retweets

A repost from X API v2 contains at maximum 140 characters from the original post. 4CAT therefore
gathers both the repost and the original post and reformats the repost text so it resembles a user's experience.

This also affects mentions, hashtags, and other data as only those contained in the first 140 characters are provided
by X API v2 with the retweet. Additional hashtags, mentions, etc. are taken from the original tweet and added
to the repost for 4CAT analysis methods. *4CAT stores the data from X API v2 as similar as possible to the format
in which it was received which you can obtain by downloading the ndjson file.*

*Example 1*

[This repost](https://x.com/tonino1630/status/1554618034299568128) returns the following data:

- *author:*    `tonino1630`
- *text:*     `RT @ChuckyFrao: ¡HUELE A LIBERTAD! La Casa Blanca publicó una orden ejecutiva sobre las acciones del Gobierno de Joe Biden para negociar p…`
- *mentions:*     `ChuckyFrao`
- *hashags:*

<br>
While the original post will return (as a reference post) this data:

- *author:*    `ChuckyFrao`
- *text:*     `¡HUELE A LIBERTAD! La Casa Blanca publicó una orden ejecutiva sobre las acciones del Gobierno de Joe Biden para negociar presos estadounidenses en otros países. #FreeAlexSaab @POTUS @usembassyve @StateSPEHA @StateDept @SecBlinken #BringAlexHome #IntegridadTerritorial https://t.co/ClSQ3Rfax0`
- *mentions:*    `POTUS, usembassyve, StateSPEHA, StateDept, SecBlinken`
- *hashtags:*    `FreeAlexSaab, BringAlexHome, IntegridadTerritorial`

<br>
As you can see, only the author of the original post is listed as a mention in the repost.

*Example 2*

[This repost](https://x.com/Macsmart31/status/1554618041459445760) returns the following:

- *author:* `Macsmart31`
- *text:* `RT @mickyd123us: @tribelaw @HonorDecency Thank goodness Biden replaced his detail - we know that Pence refused to "Take A Ride" with the de…`
- *mentions:* `mickyd123us, tribelaw, HonorDecency`

<br>
Compared with the original post referenced below:

- *author:* `mickyd123us`
- *text:* `@tribelaw @HonorDecency Thank goodness Biden replaced his detail - we know that Pence refused to "Take A Ride" with the detail he had in the basement. Who knows where they would have taken him. https://t.co/s47Kb5RrCr`
- *mentions:* `tribelaw, HonorDecency`

<br>
Because the mentioned users are in the first 140 characters of the original post, they are also listed as mentions in 
the repost.

The key difference here is that in example one the repost contains none of the hashtags or mentions from the original
post (they are beyond the first 140 characters) while the second repost example does return mentions from the original
post. *Due to this discrepancy, for reposts all mentions and hashtags of the original post are considered as mentions
and hashtags of the repost.* A user on X will see all mentions and hashtags when viewing a repost and the
repost would be a part of any network around those mentions and hashtags.
