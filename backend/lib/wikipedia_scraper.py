import requests
import ural

from backend.lib.search import Search

def WikipediaSearch(Search):
    def normalise_pagenames(self, urls):
        parsed_urls = {}
        for url in urls:
            domain = ural.get_hostname(url)
            if not domain.endswith("wikipedia.org"):
                self.dataset.log(f"{url} is not a Wikipedia URL, skipping")
                continue

            if domain.startswith("www.") or len(domain.split(".")) == 2:
                language = "en"
            else:
                language = domain.split(".")[0]

            page = url.split("/wiki/")
            if len(page) < 2:
                self.dataset.log(f"{url} is not a Wikipedia URL, skipping")
                continue

            page = page.pop().split("#")[0].split("?")[0]

            if language not in parsed_urls:
                parsed_urls[language] = set()

            parsed_urls[language].add(page)

        self.dataset.update_status(f"Collecting TOCs for {len(parsed_urls):,} Wikipedia articles.")

        # sort by language (so we can batch requests)
        result = {}
        for language, pages in parsed_urls.items():
            api_base = f"https://{language}.wikipedia.org/w/api.php"
            pages = list(pages)
            canonical_titles = []
            tocs[language] = {}

            self.dataset.update_status(f"Collecting canonical article names for articles on {language}.wikipedia.org")
            # get canonical title for URL
            while pages:
                batch = pages[:50]
                pages = pages[50:]
                canonical = requests.get(api_base, params={
                    "action": "query",
                    "format": "json",
                    "redirects": "1",
                    "titles": "|".join(batch),
                })

                for page in canonical.json()["query"]["pages"].values():
                    canonical_titles.append(page["title"])

            result[language] = canonical_titles

        return result
