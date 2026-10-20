The Weibo data source can be used to manipulate data collected from [Weibo](https://weibo.com/) with
[Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer). Data is collected with the browser extension;
4CAT cannot collect this data on its own. After collecting data with Zeeschuimer it can be uploaded to 4CAT for further
processing and analysis. See the Zeeschuimer documentation for more information on how to collect data with it.
Comments on Weibo posts are collected and imported separately, as a 'Weibo (comments)' dataset.

Data is collected as it is formatted internally by Weibo's desktop website, weibo.com. Posts are stored as (large) JSON
objects; it will usually be easier to make sense of the data by downloading it as a CSV file from 4CAT instead.

Weibo shortens long posts in feeds and lists, and sends their full text only on the post's own page. The
`body_is_shortened` column says whether a post's text was cut short when it was collected (and
`reposted_body_is_shortened` the same for the post it reposts). To collect the full text, open the post's own page
while Zeeschuimer is running.
