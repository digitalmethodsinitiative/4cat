The TikTok data source can be used to manipulate data collected from LinkedIn with 
[Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer). Data is collected with the browser extension; 
4CAT cannot collect data on its own. After collecting data with Zeeschuimer it can be uploaded to 4CAT for further
processing and analysis. See the Zeeschuimer documentation for more information on how to collect data with it.

Data is collected as it is formatted internally by TikTok's website. Posts are stored as (large) JSON objects; it will
usually be easier to make sense of the data by downloading it as a CSV file from 4CAT instead.

### Limitations

There are some annoying caveats when dealing with LinkedIn data. LinkedIn does not provide the time at which a given 
post was made; instead, it only displays relative times, e.g. "18h" if the post was created approximately 18 hours 
before it was viewed.

4CAT will try to estimate the timestamp for a post - by subtracting the relative time from the time the post was 
collected with Zeeschuimer - but this comes with its own set of issues. First, the timestamp will be less and less 
accurate the older the post is, since for older posts LinkedIn only says that it is e.g. '6 years' old - which could 
mean anything from 5 years and 6 months to 6 years and 6 months. Second, this descriptor is language-dependent. 4CAT can
interpret times in English and Dutch but (for now) not in other languages. If (approximate) timestamps are important to
you, set your interface language to one of these languages before collecting data.

A second limitation is that while thumbnail URLs are included for images embedded in posts, these are only valid for a
limited time. If images are important to you, download them as soon as possible after collecting the data. URLs seem to
expire after two months, but this may vary and it is probably best not to rely on it.

### What can you do with the data?
The main data of interest will probably be the text content of a post, which can be used with e.g. natural language 
processing processors to investigate what topics are discussed in the dataset. It can be interesting to see if certain 
people are mentioned or to see what terminology is used to discuss the topic of the post. LinkedIn supports the use of
hashtags, so for larger datasets a co-tag network can additionally be a good way to find salient topics.

4CAT can also download images from posts after creating a dataset, via the "Download images" processor. Collecting these
can be a good way to get a quick first impression of the visual aspect of LinkedIn discourse.