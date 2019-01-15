# 4CAT: Capture and Analysis Toolkit

4CAT is a tool that can be used to scrape incoming posts on forums (such as 
[4chan](https://4chan.org) and [8chan](http://8ch.net)) and then process 
them for further analysis.

A "forum", to 4CAT, is any data structure that can be represented in terms of 
threads and posts. This includes traditional forums and imageboards, but may
also encompass other types of websites such as blogs (where each blog post is a 
thread) or even Facebook pages (which also contain posts with comments).

By default, 4CAT has data source definitions for 4chan and 8chan, but it is
flexible in this regard and you can 
[add additional data sources](https://github.com/stijn-uva/4cat/wiki/Data-sources) 
with relatively little trouble as long as you keep the data structure 4CAT 
expects in mind.

It was created by [OILab](https://oilab.eu) and the 
[Digital Methods Initiative](https://www.digitalmethods.net) at the University
of Amsterdam. The tool was inspired by the 
[TCAT](https://wiki.digitalmethods.net/Dmi/ToolDmiTcat), a tool with comparable
functionality that can be used to scrape and analyse Twitter data.

4CAT is multiple things:

- A continuous forum scraper
- A search engine for the scraped corpuses
- An interface for running asynchronous analyses on CSV files
- A trend monitor (WIP)

Those things combined provide a "Capture and Analysis Toolkit", a suite of 
tools through which discourse on forums may be analysed and processed. The 
goal is to provide a straightforward aid for *chan and forum research, through 
which such platforms - often described as amorphous, volatile, or ephemeral - 
may be analysed from various epistemological perspectives.

## Components
4CAT consists of three main components, each in a separate folder:

- `backend`: A standalone Python 3 app that scrapes defined data sources, 
  downloads and stores the relevant data and performs searches and analyses as 
  queued by the front-end.
- `webtool`: A Flask app that provides a web front-end to search and analyze
  the stored data with.
- `datasources`: Data source definitions. This is a set of configuration 
  options, database definitions and python scripts to process this data with.
  If you want to set up your own data sources, refer to the
  [wiki](https://github.com/stijn-uva/4cat/wiki/Data-sources).
  
You can 
[set up 4CAT locally](https://github.com/stijn-uva/4cat/wiki/Installing-4CAT),
but we also run our own 4CAT instance which covers (among other things) some
high-traffic 4chan and 8chan boards. Access is available on request via 
[https://4cat.oilab.nl](https://4cat.oilab.nl).

## Contributing
This section yet to be written!

## Links
- [Website](https://4cat.oilab.nl)
- [Open Intelligence Lab](https://www.oilab.eu)
- [Digital Methods Initiative](https://www.digitalmethods.net)