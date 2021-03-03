# Douban Data Source

This data source allows scraping threads ('topics') and their comments from 
[Douban](https://www.douban.com/group/explore), a Chinese web forum. Douban consists of many groups, and each group 
contains topics. With this 4CAT data source, you can scrape topics for a given (list of) group(s).

Unfortunately, Douban is quite aggressive with its rate limiting, and will typically stop responding after querying more
than 500ish topics from a given group. As such, this data source is at the moment only suitable for investigating recent
activity on the platform.

It may be possible to implement a solution for this using Proxies or Tor. Apart from this issue, the data source is in
principle set up to allow scraping the full Douban website.

## Acknowledgements
Thanks to Tong Wu for introducing the platform and helping us find our way in it.