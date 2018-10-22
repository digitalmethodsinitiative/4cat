# 4CAT: Capture and Analysis Tool

4CAT is a tool that can be used to scrape incoming posts on the imageboard [4chan](https://4chan.org)
and then process them for further analysis.

It was created by [OILab](https://oilab.eu) and the [Digital Methods Initiative](https://www.digitalmethods.net),
both based at the University of Amsterdam. The tool was inspired by the 
[TCAT](https://wiki.digitalmethods.net/Dmi/ToolDmiTcat), a tool with comparable
functionality that can be used to scrape and analyse Twitter data.

## Contents
- `backend`: A standalone Python 3 app that scrapes 4chan, downloads and 
  stores the relevant data and performs searches and analyses as queued by 
  the front-end.
- `webtool`: A Flask app that provides a web front-end to search and analyze
  the stored 4chan archives with.
  
If you want to run 4CAT yourself, please refer to [the Wiki](https://github.com/stijn-uva/4cat/wiki/Installing-4CAT) for instructions
on how to install 4CAT locally.

## Contributing
This section yet to be written!

## Links
- [Website](https://4cat.oilab.nl)