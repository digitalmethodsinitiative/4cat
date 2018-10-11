# 4CAT: Capture and Analysis Tool

## Contents
- `backend`: A standalone Python 3 app that scrapes 4chan, downloads and 
  stores the relevant data and performs searches and analyses as queued by 
  the front-end.
- `webtool`: A Flask app that provides a web front-end to search and analyze
  the stored 4chan archives with.

See the README files in the respective folders for more information. See
`requirements.txt` for dependencies, and install them with

```
pip3 install -r requirements.txt
```

4CAT furthermore requires a PostgreSQL (at least version 9.5) database, and a 
user with access to it. Depending on the boards you want to capture and/or
analyze, it also requires a lot of disk space (up to multiple terabytes for
large and/or multiple boards).

## Configuration
Before running anything, copy `config.py-example` to `config.py` and edit as 
needed. Options are documented within.

## Links
- [Website](https://4cat.oilab.nl)