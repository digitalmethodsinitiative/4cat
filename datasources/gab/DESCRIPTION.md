The Gab data source can be used to manipulate data collected from gab.com with 
[Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer). Data is collected with the browser extension; 
4CAT cannot collect data on its own. After collecting data with Zeeschuimer it can be uploaded to 4CAT for further
processing and analysis. See the Zeeschuimer documentation for more information on how to collect data with it.

Data is collected as it is formatted internally by Gab's website. Posts are stored as (large) JSON objects; it 
will usually be easier to make sense of the data by downloading it as a CSV file from 4CAT instead.

### Data format
Most data attributes map to 4CAT's CSV export quite straightforwardly.