The Threads data source can be used to manipulate data collected from [Threads](https://threads.com) - Meta's 
microblogging platform - with  [Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer). Data is collected 
with the browser extension; 4CAT cannot collect data on its own. After collecting data with Zeeschuimer it can be 
uploaded to 4CAT for further processing and analysis. See the Zeeschuimer documentation for more information on how to 
collect data with it.

Data is collected as it is formatted internally by Threads' website. Posts are stored as (large) JSON objects; it 
will usually be easier to make sense of the data by downloading it as a CSV file from 4CAT instead. The JSON structure
is relatively straightforward and contains some data not included in the CSV exports.