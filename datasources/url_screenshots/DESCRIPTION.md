This data source uses [Selenium](https://selenium-python.readthedocs.io/) in combination with
a [Firefox webdriver](https://github.com/mozilla/geckodriver/releases) and Firefox for linux
to make screenshots of web pages.

The data source loads a browser "behind the scenes" that visits the given URL and takes a screenshot after waiting for
a page to finish loading.

Note that screenshots may not look the same as they would look like on your own device. The page may render differently
or load slower than you are expecting due to geolocation, slow connections, different resolutions, et cetera.