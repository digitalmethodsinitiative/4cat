The BitChute data source collects data from the BitChute websites via web scraping. Datasets created are thus a 
reflection of what you can find through the website at the time of creating the dataset. 4CAT uses BitChute's own search
function to find videos for a given query.

BitChute videos may be blocked for a variety of reasons, e.g. violating content guidelines. Such videos will still be
included in the dataset, but some metadata will be missing and the 'category' field for the video will contain the
reason the video is unavailable. It is also not possible to collect comments for blocked videos.

Some content is only blocked when requested from a certain geographical location, e.g. because it violates local laws.
In that case results will depend on where the server you're running 4CAT on is physically located, e.g. in The 
Netherlands videos containing denials of the holocaust are blocked but they may be available when using BitChute from
another country. It can be useful to check if a video reported as blocked by 4CAT is actually available from your own
browser.

### Levels of detail
Data can be collected at three levels of detail: basic, detailed, and detailed with comments. The more detail you want,
the longer a query will take. Basic datasets only collect video metadata from search results; 'detailed' datasets also
request the video page for each video, which allows the collection of more metadata such as the video category. 
Collecting comments can take an especially long time, proportional to the amount of comments a video has, so this is
only recommended if you are certain you need them for your analysis.

### What can you do with the data?
The video title and description can be analysed as text, for example to see if certain people are mentioned or to see
what terminology is used to discuss the topic of the video. Many videos also link to related sites in the video 
description. For example, they may link to a page where viewers can donate to the video creator. A link analysis of the
results can thus be interesting.

When collecting videos for a certain keyword, it can also be useful to analyse what channels the videos in the dataset
are from. Often, there are particular channels that 'specialize' in a specific topic, which can then be interesting to
analyse in more detail (for example by creating a new dataset with all their videos).

4CAT can also download video thumbnails after creating a dataset, via the "Download images" processor. Collecting these
can be a good way to get a quick first impression of the types of videos in the dataset.