The RedNote data source can be used to manipulate data collected from [RedNote](https://www.xiaohongshu.com/) - also 
known as Xiaohongshu or Little Red Book - with  [Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer). Data is collected with the browser extension; 4CAT 
cannot collect data on its own. After collecting data with Zeeschuimer it can be uploaded to 4CAT for further processing 
and analysis. See the Zeeschuimer documentation for more information on how to collect data with it.

Data is collected as it is formatted internally by RedNote' website. Posts are stored as (large) JSON objects; it 
will usually be easier to make sense of the data by downloading it as a CSV file from 4CAT instead. The JSON structure
is relatively straightforward and contains some data not included in the CSV exports.

Note that depending on the page data is captured from, some metadata may not be available. For example, when capturing 
data from the 'Explore' page, the description and time of posting of a post are not available. These are however 
available when capturing from a post's page. After importing a dataset to 4CAT, the dataset status will summarise what
information is and is not available. A `missing_fields` column additionally contains the names of columns with missing 
data for each imported item.