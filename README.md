# ![](https://github.com/digitalmethodsinitiative/4cat/tree/master/common/assets/logo_readme.png) 4CAT: Capture and Analysis Toolkit

[![DOI: 10.5281/zenodo.4742622](https://zenodo.org/badge/DOI/10.5281/zenodo.4742622.svg)](https://doi.org/10.5281/zenodo.4742622)
[![License: MPL 2.0](https://img.shields.io/badge/license-MPL--2.0-informational)](https://github.com/digitalmethodsinitiative/4cat/blob/master/LICENSE)
[![Requires Python 3.8](https://img.shields.io/badge/python-v3.8-blue)](https://www.python.org/)
[![Docker Image CI Status](https://github.com/digitalmethodsinitiative/4cat/workflows/Docker%20Image%20CI/badge.svg)](https://github.com/digitalmethodsinitiative/4cat/actions/workflows/dockerimage.yml)

<p align="center"><img alt="A screenshot of 4CAT, displaying its 'Create Dataset' interface" src="common/assets/screenshot1.png"><img alt="A screenshot of 4CAT, displaying a network visualisation of a dataset" src="common/assets/screenshot2.png"></p>

4CAT is a research tool that can be used to analyse and process data from
online social platforms. Its goal is to make the capture and analysis of data
from these platforms accessible to people through a web interface, without
requiring any programming or web scraping skills. Our target audience is
researchers, students and journalists interested using Digital Methods in their
work.

In 4CAT, you create a dataset from a given platform according to a given set of
parameters; the result of this (usually a CSV file containing matching items)
can then be downloaded or analysed further with a suite of analytical
'processors', which range from simple frequency charts to more advanced analyses
such as the generation and visualisation of word embedding models.

4CAT has a (growing) number of supported data sources corresponding to popular
platforms that are part of the tool, but you can also [add additional data
sources](https://github.com/digitalmethodsinitiative/4cat/wiki/How-to-make-a-data-source)
using 4CAT's Python API. The following data sources are currently supported
actively:

* 4chan
* 8kun
* Bitchute
* Parler
* Reddit
* Telegram
* Twitter API (Academic and regular tracks)

The following platforms are supported through other tools, from which you can
import data into 4CAT for analysis:

* Facebook (via [CrowdTangle](https://www.crowdtangle.com) exports)
* Instagram (via CrowdTangle)
* TikTok (via
  [Zeeschuimer](https://github.com/digitalmethodsinitiative/zeeschuimer) or
  [tiktok-scraper](https://github.com/drawrowfly/tiktok-scraper))

A number of other platforms have built-in support that is untested, or requires
e.g. special API access. You can view the [full list of data
sources](https://github.com/digitalmethodsinitiative/4cat/tree/master/datasources)
in the GitHub repository.

## Install
You can install 4CAT locally or on a server via Docker or manually. Copying our docker-compose_prod.yml file and using

```
docker-compose -f docker-compose_prod.yml up
```

will pull the lastest version from Docker Hub, but detailed and alternative installation instructions are available
[in our
wiki](https://github.com/digitalmethodsinitiative/4cat/wiki/Installing-4CAT).
Currently 4chan, 8chan, and 8kun require additional steps; please see the wiki.

Please check our
[issues](https://github.com/digitalmethodsinitiative/4cat/issues) and create
one if you experience any problems (pull requests are also very welcome).

## Components
4CAT consists of several components, each in a separate folder:

- `backend`: A standalone daemon that collects and processes data, as queued via
  the tool's web interface or API.
- `webtool`: A Flask app that provides a web front-end to search and analyze
  the stored data with.
- `common`: Assets and libraries.
- `datasources`: Data source definitions. This is a set of configuration
  options, database definitions and python scripts to process this data with.
  If you want to set up your own data sources, refer to the
  [wiki](https://github.com/digitalmethodsinitiative/4cat/wiki/How-to-make-a-data-source).
- `processors`: A collection of data processing scripts that can plug into
  4CAT to manipulate or process datasets created with 4CAT. There is an API
  you can use to [make your own
  processors](https://github.com/digitalmethodsinitiative/4cat/wiki/How-to-make-a-processor).

## Credits & License
4CAT was created at [OILab](https://oilab.eu) and the
[Digital Methods Initiative](https://www.digitalmethods.net) at the University
of Amsterdam. The tool was inspired by
[DMI-TCAT](https://wiki.digitalmethods.net/Dmi/ToolDmiTcat), a tool with
comparable  functionality that can be used to scrape and analyse Twitter data.

4CAT development is supported by the Dutch [PDI-SSH](https://pdi-ssh.nl/en/)
foundation through the [CAT4SMR project](https://cat4smr.humanities.uva.nl/).

4CAT is licensed under the Mozilla Public License, 2.0. Refer to the `LICENSE`
file for more information.
