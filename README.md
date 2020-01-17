# 4CAT: Capture and Analysis Toolkit

4CAT is a tool that can be used to analyse and process data from forum-like
platforms (such as [Reddit](https://www.reddit.com), [4chan](https://4chan.org)
or [Telegram](https://www.telegram.com)) for research purposes.

A "forum", to 4CAT, is any data structure that can be represented in terms of 
threads and posts. This includes traditional forums and imageboards, but may
also encompass other types of websites such as blogs (where each blog post is a 
thread) or even Facebook pages (which also contain posts with comments).

By default, 4CAT has a number of data sources corresponding to popular forums
that can be configured to retrieve data from those platforms, but you can also
[add additional data sources](https://github.com/stijn-uva/4cat/wiki/Data-sources) 
with relatively little trouble as long as you keep the data structure 4CAT 
expects in mind.

4CAT was created by [OILab](https://oilab.eu) and the 
[Digital Methods Initiative](https://www.digitalmethods.net) at the University
of Amsterdam. The tool was inspired by the 
[TCAT](https://wiki.digitalmethods.net/Dmi/ToolDmiTcat), a tool with comparable
functionality that can be used to scrape and analyse Twitter data.

4CAT is multiple things:

- A search engine for scraped corpora
- A transparent and modular analysis toolkit
- A means to produce traceable and reproducible digital media research

Those things combined provide a "Capture and Analysis Toolkit", a suite of 
tools through which discourse on forums may be analysed and processed. The 
goal is to provide a straightforward aid for *chan and forum research, through 
which such platforms - often described as amorphous, volatile, or ephemeral - 
may be analysed from various epistemological perspectives.

## Components
4CAT consists of several components, each in a separate folder:

- `backend`: A standalone Python 3 app that scrapes defined data sources, 
  downloads and stores the relevant data and performs searches and analyses as 
  queued by the front-end.
- `webtool`: A Flask app that provides a web front-end to search and analyze
  the stored data with.
- `datasources`: Data source definitions. This is a set of configuration 
  options, database definitions and python scripts to process this data with.
  If you want to set up your own data sources, refer to the
  [wiki](https://github.com/stijn-uva/4cat/wiki/Data-sources).
- `processors`: A collection of data processing scripts that can plug into
  4CAT and manipulate or process datasets created with 4CAT. There is an API
  you can use to [make your own processors](https://github.com/digitalmethodsinitiative/4cat/wiki/How-to-make-a-processor).
  
You can 
[set up 4CAT locally](https://github.com/stijn-uva/4cat/wiki/Installing-4CAT),
but we also run our own 4CAT instance which covers (among other things) some
high-traffic 4chan and 8chan boards. Access is available on request.

## Contributing
This section yet to be written!

## License

4CAT is licensed under the Mozilla Public License, 2.0. Refer to the `LICENSE`
file for more information.

## Links
- [Open Intelligence Lab](https://www.oilab.eu)
- [Digital Methods Initiative](https://www.digitalmethods.net)