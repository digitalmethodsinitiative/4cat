The TikTok data source can be used to manipulate data collected from TikTok with 
[Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer). Data is collected with the browser extension; 
4CAT cannot collect data on its own. After collecting data with Zeeschuimer it can be uploaded to 4CAT for further
processing and analysis. See the Zeeschuimer documentation for more information on how to collect data with it.

Data is collected as it is formatted internally by TikTok's website. Posts are stored as (large) JSON objects; it 
will usually be easier to make sense of the data by downloading it as a CSV file from 4CAT instead.

### Limitations
TikTok datasets contain links to e.g. thumbnails and video files. Due to how TikTok works, these expire; they will work 
for a couple of hours after capture, but become unavailable soon after. If you plan to e.g. download images or videos, 
do so as soon as possible after capturing the data.

It is currently not possible to download and analyse comments with 4CAT or Zeeschuimer.