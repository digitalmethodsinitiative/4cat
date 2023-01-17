The Imgur data source can be used to manipulate data collected from 9gag.com with 
[Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer). Data is collected with the browser extension; 
4CAT cannot collect data on its own. After collecting data with Zeeschuimer it can be uploaded to 4CAT for further
processing and analysis. See the Zeeschuimer documentation for more information on how to collect data with it.

Data is collected as it is formatted internally by Imgur's website. Posts are stored as (large) JSON objects; it 
will usually be easier to make sense of the data by downloading it as a CSV file from 4CAT instead.

### Data format
Most data attributes map to 4CAT's CSV export quite straightforwardly. Imgur data has a few interesting attributes; 
posts have a `virality_score` (unclear what this means exactly) and have a number of other metrics that can be useful
to filter content (upvotes, downvotes, favourites and the amount of comments).

### Limitations
Imgur only refers to the author of a post by a numerical ID; the author's full details are only loaded when clicking 
through to an individual post's page.

Imgur posts show up as a single image or video on the site's index page, but are often in fact galleries that contain
multiple images. In 4CAT items will refer to first image or video in a gallery only; the `album_media` column in the CSV
output will contain the total amount of images in the post. 