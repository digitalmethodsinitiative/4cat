This data source allows scraping threads and their posts from [LIHKG](https://lihkg.com/), a Chinese web forum mostly 
popular in Hong Kong. LIHKG is formatted mostly like a traditional web forum, with threads and posts.

### Dataset format
Each item in a dataset corresponds to a post on LIHKG. If a post was the first post in a thread, it will have some extra
metadata related to the thread, e.g. its title.

### Behind the scenes
The data source uses LIHKG's web API - i.e. the one LIHKG's web interface uses to asynchronously load data. Since this 
API is not primarily intended for third-party usage, there may be undocumented quirks and it could break without notice
(in which case we encourage you to [file an issue](https://github.com/digitalmethodsinitiative/4cat/issues)). At the 
time of writing, it seems reasonably reliable and stable, and relatively large datasets can be created with 4CAT without
much trouble.