The Telegram data source collects messages from channels or groups. You can optionally only collect messages within a 
given date range, or only a given amount of messages per channel/group. 

Note that due to how Telegram works, you need to know what channels or groups you want to collect data from before you 
collect it; you cannot search by keyword as you can for some other platforms. You can, however, use the search function 
in the Telegram app to find groups and channels, and then collect messages from the ones you find with 4CAT.

Another way of finding relevant groups is through a standard web search engine, like Google. Search for, for example,
[`bill gates site:t.me`](https://www.google.com/search?q=bill+gates+site:t.me&hl=en&filter=0&dpr=2) on Google to find 
Telegram groups Google has indexed that mention 'Bill Gates'. This is never a complete picture, but can be a good way 
to get started.

### Technical details and caveats
Telegram data is collected via Telegram's [official API](https://core.telegram.org/) via the
[MTProto](https://core.telegram.org/mtproto) protocol. This is done using the [Telethon 
library](https://docs.telethon.dev/) for Python. Everything that happens in a channel or group within the parameters 
is collected, though "actions" (such as someone joining or leaving a channel) are ignored. The resulting dataset then 
comprises messages from users and their metadata. 

If a message contains an attachment, the metadata of that attachment is recorded. This can then be used to download e.g.
the attached image, but only if the 'Save session' option was checked when creating the dataset. If a message contains 
multiple attachments, these are included and counted as separate messages (one of these will contain the actual message 
text).

### Data format
Messages are saved as JSON objects, combined in one [NDJSON](http://ndjson.org/) file. For each message, the object 
collected with Telethon is mapped to JSON. A lot of information is included per message, more than can be explained 
here. The data is roughly congruent with [this 
documentation](https://docs.telethon.dev/en/stable/modules/custom.html#telethon.tl.custom.message.Message). Most 
metadata you may be interested in is included or can be derived from the included data.

NDJSON files can also be downloaded as a CSV file in 4CAT. In this case, only the most important attributes
of a message (such as message text, timestamp, author name, and whether it was forwarded) are included in the CSV file.

### What can you do with the data?
Telegram data lends itself well to text analysis, since for each message the full message text is captured. When 
capturing messages from multiple groups, it can also be interesting to create a bipartite user-chat network, to see
if particular users are present in multiple groups.

4CAT can also download attached images and video thumbnails after creating a dataset, via the "Download Telegram 
images" processor.

### Further reading
The following article offers some meditations on how to design data-driven Telegram research.

* Peeters, S., & Willaert, T. (2022). Telegram and Digital Methods: Mapping Networked Conspiracy Theories through
  Platform Affordances. <i>M/C Journal</i>, 25(1). [https://doi.org/10.5204/mcj.2878](https://doi.org/10.5204/mcj.2878)