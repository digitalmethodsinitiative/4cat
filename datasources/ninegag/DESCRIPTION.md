The 9gag data source can be used to manipulate data collected from 9gag.com with 
[Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer). Data is collected with the browser extension; 
4CAT cannot collect data on its own. After collecting data with Zeeschuimer it can be uploaded to 4CAT for further
processing and analysis. See the Zeeschuimer documentation for more information on how to collect data with it.

Data is collected as it is formatted internally by 9gag's website. Posts are stored as (large) JSON objects; it 
will usually be easier to make sense of the data by downloading it as a CSV file from 4CAT instead.

### Data format
Most data attributes map to 4CAT's CSV export quite straightforwardly. 9gag seems to annotate posts automatically using 
a machine learning model. In 4CAT's CSV export, these annotations are collected in the 'tags_annotated' column. 

### Limitations
9gag posts can be anonymous. In the 9gag interface, anonymous posts show up as made by the user '9GAGGER'. In some cases
they additionally have no timestamp. 4CAT's CSV export marks such posts with a 'yes' value in the 'is_anonymous' column
and the '9GAGGER' name in the 'author' column. Timestamps for posts with no timestamp show up as '1 January 1970', as 
this is what the value used by TikTok internally converts to. 