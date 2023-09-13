The Douyin data source can be used to manipulate data collected from douban.com with 
[Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer). Data is collected with the browser extension; 
4CAT cannot collect data on its own. After collecting data with Zeeschuimer it can be uploaded to 4CAT for further
processing and analysis. See the Zeeschuimer documentation for more information on how to collect data with it.

Data is collected as it is formatted internally by Douyin's website. Posts are stored as (large) JSON objects; it 
will usually be easier to make sense of the data by downloading it as a CSV file from 4CAT instead.

### Data format
The data collected from Zeeschuimer is very comprehensive and varies depending on where from Douyin.com the data was
collected (the `post_source_domain` field can be used to determine from which page the data was collected). Common 
data attributes are mapped to 4CAT's preview and CSV export, however, the raw NDJSON file contains a great deal more. 
If you are not familiar with NDJSON files, you can use the "Convert NDJSON file to CSV" processor to create a CSV using 
the complex nested keys in each JSON. If some of these features seem relevant for research, please feel free to [make 
an issue on 4CAT](https://github.com/digitalmethodsinitiative/4cat/issues) and let us know what these field represent.

Sometimes, particularly when searching, Douyin returns a "collection" of videos instead of a single video. While the 
videos will autoplay sequentially, we added the `4CAT_first_video_displayed` field to denote the first video in the 
collection as well as any single videos. You can therefore filter by this field if you would like to remove the other
videos in collections that may have not actually been viewed/shown to the user.

### Limitations
Mentions unfortunately do not contain the username in the raw data (it appears this information is obtained through
another method not captured currently by Zeeschuimer). We instead use links pointing to the user's profile.

Due to the varying nature of the data objects depending on where on Douyin they are obtained, it appears some 
information may be missing that could be obtained by observing a video on a different page. If that information is 
found elsewhere in the JSON, please make an issue to inform us of where it can be obtained.