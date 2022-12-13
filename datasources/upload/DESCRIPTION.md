You can upload a CSV or TAB files to 4CAT. After upload, these will be available for further analysis and processing. 
Files need to be encoded with the UTF-8 encoding.

### Importing from a tool
4CAT can recognise the output formats of a number of tools. If you are uploading a csv file exported from such a tool,
select it in the 'CSV format' drop-down box and it will automatically be converted to be 4CAT-compatible.

### Formatting your data
A variety of formats may be uploaded. If 4CAT is not familiar with the format (i.e. if it is not listed in the 'CSV 
format' drop-down box) you will be asked to provide the column mapping yourself. This means that you need to indicate
which column contains an item's ID, timestamp, and so on.

If your file contains hashtags, name the column tags or hashtags and make sure they are comma-separated. 

4CAT will attempt to parse a variety of date and time formats, but for best results it is recommended to format dates
as `HH-MM-DD hh:mm:ss`.