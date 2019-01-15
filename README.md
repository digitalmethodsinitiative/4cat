# 4CAT: Capture and Analysis Toolkit

4CAT is a tool that can be used to scrape incoming posts on the imageboards [4chan](https://4chan.org)
and [8chan](http://8ch.net) and then process them for further analysis.

It was created by [OILab](https://oilab.eu) and the [Digital Methods Initiative](https://www.digitalmethods.net),
both based at the University of Amsterdam. The tool was inspired by the 
[TCAT](https://wiki.digitalmethods.net/Dmi/ToolDmiTcat), a tool with comparable
functionality that can be used to scrape and analyse Twitter data.

4CAT is multiple things:

- A continuous image board scraper
- A search engine for the scraped 4chan corpus
- An interface for running asynchronous analyses on CSV files
- A trend monitor (WIP)

Those things combined provide a "Capture and Analysis Toolkit", a suite of 
tools through which discourse on image boards may be analysed and processed. 
The goal is to provide a straightforward aid for chan research, through which
this platform - often described as amorphous, volatile, or ephemeral - may
be analysed from various epistemological perspectives.

## Components
4CAT consists of two main components, each in a separate folder:

- `backend`: A standalone Python 3 app that scrapes 4/8chan, downloads and 
  stores the relevant data and performs searches and analyses as queued by 
  the front-end.
- `webtool`: A Flask app that provides a web front-end to search and analyze
  the stored 4chan archives with.
  
Access 4CAT is available on request via [https://4cat.oilab.nl](https://4cat.oilab.nl).

If you want to run 4CAT yourself, please refer to 
[the Wiki](https://github.com/stijn-uva/4cat/wiki/Installing-4CAT) for 
instructions on how to install 4CAT locally.

## Contributing
This section yet to be written!

## Links
- [Website](https://4cat.oilab.nl)
- [Open Intelligence Lab](https://www.oilab.eu)
- [Digital Methods Initiative](https://www.digitalmethods.net)