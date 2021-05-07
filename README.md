# 4CAT: Capture and Analysis Toolkit

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.4742623.svg)](https://doi.org/10.5281/zenodo.4742623)

4CAT is a tool that can be used to analyse and process data from online social
platforms. Its goal is to make the capture and analysis of data from these 
platforms accessible to people through a web interface, without requiring any
programming or web scraping skills.

In 4CAT, you create a dataset from a given platform according to a given set of
parameters; the result of this (usually a CSV file containing matching items) 
can then be downloaded or analysed further with a suite of analytical 
'processors', which range from simple frequency charts to more advanced analyses
such as the generation and visualisation of word embedding models.

4CAT has a (growing) number of supported data sources corresponding to popular 
platforms that are part of the tool, but you can also [add additional data 
sources](https://github.com/digitalmethodinitiative/4cat/wiki/Data-sources) 
using 4CAT's Python API. The following data sources are currently supported 
actively:

* 4chan
* 8kun
* Bitchute
* Parler
* Reddit
* Telegram
* Twitter API (Academic Track, full-archive search)

The following platforms are supported through other tools, from which you can 
import data into 4CAT for analysis:

* Facebook (via [CrowdTangle](https://www.crowdtangle.com) exports)
* Instagram (via CrowdTangle)
* TikTok (via [tiktok-scraper](https://github.com/drawrowfly/tiktok-scraper))

A number of other platforms have built-in support that is untested, or requires
e.g. special API access. You can view the [full list of data 
sources](https://github.com/digitalmethodsinitiative/4cat/tree/master/datasources) 
in the GitHub repository.

## Install
We use 4CAT for our own purposes at the University of Amsterdam but you can
(and are encouraged to!) run your own instance. [You can find detailled 
installation instructions in our 
wiki](https://github.com/stijn-uva/4cat/wiki/Installing-4CAT).

Support for Docker is work-in-progress. You can install using 
[docker-compose](https://docs.docker.com/compose/install/) by running:
```
docker-compose up
```

But this may currently not work in all environments. We hope to rectify this in 
the future (pull requests are very welcome).

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
  you can use to [make your own 
  processors](https://github.com/digitalmethodsinitiative/4cat/wiki/How-to-make-a-processor).

## Contributing
This section yet to be written!

## Credits & License
4CAT was created by [OILab](https://oilab.eu) and the 
[Digital Methods Initiative](https://www.digitalmethods.net) at the University
of Amsterdam. The tool was inspired by the 
[TCAT](https://wiki.digitalmethods.net/Dmi/ToolDmiTcat), a tool with comparable
functionality that can be used to scrape and analyse Twitter data.

4CAT development is supported by the Dutch [PDI-SSH](https://pdi-ssh.nl/en/) foundation through the [CAT4SMR project](https://cat4smr.humanities.uva.nl/). 

4CAT is licensed under the Mozilla Public License, 2.0. Refer to the `LICENSE`
file for more information.

## Links
- [Open Intelligence Lab](https://www.oilab.eu)
- [Digital Methods Initiative](https://www.digitalmethods.net)