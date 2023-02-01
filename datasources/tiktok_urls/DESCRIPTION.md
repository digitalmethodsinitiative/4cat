This TikTok data source retrieves metadata of posts from a given list of video URLs.

It can only operate on direct video links, i.e. not with links to hashtags, accounts or sounds. For videos, it 
retrieves the page for that video from the web interface 
[example](https://www.tiktok.com/@willsmith/video/7079929224945093934) and then extracts the metadata embedded in the 
page's source code. This is much faster than some of the alternative approaches (such as controlling a full browser)
and as long as the requests are paced appropriately, TikTok does not seem to block 4CAT.

The downside is that the data source is limited to what data is embedded on the page. This is a lot - and includes the 
first 20 or so comments - but it is not possible to e.g. retrieve more comments than that.

For more hands-on, flexible TikTok data capture, take a look at 
[Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer), the data capture browser extension that is a 
companion to 4CAT.