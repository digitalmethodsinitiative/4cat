The Pinterest data source can be used to manipulate data collected from [Pinterest](https://pinterest.com/) with  
[Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer). Data is collected with the browser extension; 4CAT cannot collect data on its own. After collecting 
data with Zeeschuimer it can be uploaded to 4CAT for further processing and analysis. See the Zeeschuimer documentation 
for more information on how to collect data with it.

Data is collected as it is formatted internally by Pinterest's website. Posts are stored as (large) JSON objects; it 
will usually be easier to make sense of the data by downloading it as a CSV file from 4CAT instead. The JSON structure
is relatively straightforward and contains some data not included in the CSV exports.

## Missing data

Pinterest does not always include all metadata in its JSON objects; on some pages, the time the post was made is missing
from a post, for example. 4CAT will warn you about this when importing data. 