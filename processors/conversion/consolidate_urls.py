"""
Consolidate URLs using rules
"""
import csv
from urllib.parse import urlparse, urlunparse

from processors.conversion.extract_urls import ExtractURLs
from common.lib.exceptions import ProcessorInterruptedException
from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class ConsolidateURLs(BasicProcessor):
    """

    """
    type = "consolidate-urls"  # job type ID
    category = "Conversion"  # category
    title = "Consolidate URLs"  # title displayed in UI
    description = "Retain only domain (and optionally path) of URLs; used for Custom Networks (e.g. author + domains)"
    extension = "csv"

    options = {
        "column": {
            "type": UserInput.OPTION_TEXT,
            "help": "URL column to consolidate",
            "default": "url",
            "inline": True,
            "tooltip": "Accepts column with comma seperated URLs",
        },
        "expand_urls": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Expand shortened URLs",
            "tooltip": "This can take a long time for large datasets and it is NOT recommended to run this processor on datasets larger than 10,000 items.",
        },
        "method": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Method of URL consolidation",
            "options": {
                "domain": "Domain only",
                "custom": "Customize rules (use settings below)",
                "social_media": "Social Media rules; overrides other options",
            },
            "default": "basics",
            "tooltip": "Social Media rules are predefined and available via GitHub link."
        },
        "remove_scheme": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Remove scheme (e.g., 'http', 'https', etc.)",
        },
        "remove_path": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Remove path (e.g., '/path/to/article')",
        },
        "remove_query": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Remove query (e.g., '?query=search_term' or '?ref=newsfeed')",
        },
        "remove_parameters": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Remove parameters (e.g., ';key1=value1')",
        },
        "remove_fragments": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Remove fragments (e.g., '#fragment')",
        },
    }

    # Common domain prefaces to remove
    domain_prefaces = ["m", "www"]
    # Domain dictionary (after domain_prefaces are removed)  with additional rules based on URL components to conform to "clean URLs"
    social_media_rules = {
        "facebook.com": [
            {
                "rule": lambda parsed_url: True if "events" == parsed_url.path.split("/")[1] else False,
                "result": lambda parsed_url: "facebook.com/events/" + parsed_url.path.rstrip("/").split("/")[-1]
            },
            {
                "rule": lambda parsed_url: True if "groups" == parsed_url.path.split("/")[1] else False,
                "result": lambda parsed_url: "facebook.com/groups/" + parsed_url.path.rstrip("/").split("/")[-1]
            },
            {
                # profiles, stories, and permanent links are directed back to User main page
                "rule": lambda parsed_url: True if any([page in parsed_url.path.lstrip("/").split("/")[0] for page in ["profile.php", "story.php", "permalink.php"]]) else False,
                "result": lambda parsed_url: "facebook.com/" + {query.split("=")[0]: (query.split("=")[1] if len(query.split("=")) >= 2 else "") for query in parsed_url.query.split("&")}.get("id", "")
            },
            {
                # Link to photos with photo.php
                "rule": lambda parsed_url: True if any([page in parsed_url.path.lstrip("/").split("/")[0] for page in
                                                        ["photo.php"]]) else False,
                "result": lambda parsed_url: "facebook.com/" + ("photo.php?fbid=" + {query.split("=")[0]: query.split("=")[1] for query in
                                                                parsed_url.query.split("&")}.get("fbid")) if "fbid" in {query.split("=")[0]: query.split("=")[1] for query in
                                                                parsed_url.query.split("&")} else parsed_url.path.lstrip("/")
            },
            {
                "rule": lambda parsed_url: True if "photos" in parsed_url.path.split("/") else False,
                "result": lambda parsed_url: "facebook.com/photo.php?fbid=" + parsed_url.path.strip("/").split("/")[-1]
            },
            {
                # link to video (without any user indication in URL)
                "rule": lambda parsed_url: True if parsed_url.path.split("/")[1] == "watch" else False,
                "result": lambda parsed_url: "facebook.com/watch/?v=" + ConsolidateURLs.create_query_dictionary(parsed_url.query).get("v", "")
            },
            {
                # Hashtag
                "rule": lambda parsed_url: True if "hashtag" == parsed_url.path.lstrip("/").split("/")[0] else False,
                "result": lambda parsed_url: "facebook.com/hashtag/" + parsed_url.path.strip("/").split("/")[-1]
            },
            {
                # If NONE of the above are true, attempt to return link to user profile (TODO: these may not be inclusive)
                "rule": lambda parsed_url: True if parsed_url.path else False,
                "result": lambda parsed_url: "facebook.com/" + parsed_url.path.split("/")[1]
            },
        ],
        "instagram.com": [
            {
                # For moment, we'll return path only; need more test URLs
                "rule": lambda parsed_url: True,
                "result": lambda parsed_url: urlunparse(ConsolidateURLs.remove_url_components(parsed_url,
                                                                                   remove_scheme=True,
                                                                                   remove_query=True,
                                                                                   remove_params=True,
                                                                                   remove_fragment=True)).lstrip("/")

            },
        ],
        "rumble.com": [
            {
                # Embeded videos
                "rule": lambda parsed_url: True if "embed" == parsed_url.path.lstrip("/").split("/")[0] else False,
                "result": lambda parsed_url: "rumble.com/" + parsed_url.path.strip("/").split("/")[-1]
            },
            {
                # User page
                "rule": lambda parsed_url: True if "user" == parsed_url.path.lstrip("/").split("/")[0] else False,
                "result": lambda parsed_url: "rumble.com/user/" + parsed_url.path.strip("/").split("/")[-1]
            },
            {
                "rule": lambda parsed_url: True,
                "result": lambda parsed_url: "rumble.com/" + parsed_url.path.strip("/").split("-")[0]
            }
        ],
        "t.me": [
            {
                # s/channel
                "rule": lambda parsed_url: True if "s" == parsed_url.path.strip("/").split("/")[0] else False,
                "result": lambda parsed_url: "t.me/" + parsed_url.path.strip("/").split("/")[-1]
            },
            {
                # channel or user
                "rule": lambda parsed_url: True,
                "result": lambda parsed_url: "t.me/" + parsed_url.path.strip("/").split("/")[0]
            }
        ],
        "twitter.com": [
            # Attempt to resolve to Username
            {
                # No Username in URL
                "rule": lambda parsed_url: True if "i" == parsed_url.path.strip("/").split("/")[0] else False,
                "result": lambda parsed_url: "twitter.com/" + parsed_url.path.strip("/")
            },
            {
                "rule": lambda parsed_url: True,
                "result": lambda parsed_url: "twitter.com/" + parsed_url.path.strip("/").split("/")[0]
            }
        ],
        "youtube.com": [
            {
                # Channels
                "rule": lambda parsed_url: True if any([page == parsed_url.path.lstrip("/").split("/")[0] for page in ["c", "channel"]]) else False,
                "result": lambda parsed_url: "youtube.com/" + parsed_url.path.lstrip("/").split("/")[-1]
            },
            {
                # Shorts
                "rule": lambda parsed_url: True if any(
                    [page == parsed_url.path.lstrip("/").split("/")[0] for page in ["shorts"]]) else False,
                "result": lambda parsed_url: "youtube.com/shorts/" + parsed_url.path.lstrip("/").split("/")[-1]
            },
            {
                # Playlist
                "rule": lambda parsed_url: True if "playlist" == parsed_url.path.lstrip("/").split("/")[0].lower() else False,
                "result": lambda parsed_url: "youtube.com/" + ("playlist?list=" + ConsolidateURLs.create_query_dictionary(parsed_url.query).get("list")) if "list" in ConsolidateURLs.create_query_dictionary(parsed_url.query) else parsed_url.path.lstrip("/")
            },
            {
                # Videos
                "rule": lambda parsed_url: True if "watch" == parsed_url.path.lstrip("/").split("/")[0].lower() else False,
                "result": lambda parsed_url: "youtube.com/" + ("watch?v=" + ConsolidateURLs.create_query_dictionary(parsed_url.query).get("v")) if "v" in ConsolidateURLs.create_query_dictionary(parsed_url.query) else parsed_url.path.lstrip("/")
            },
            {
                # Users
                "rule": lambda parsed_url: True if ("user" == parsed_url.path.lstrip("/").split("/")[0].lower() or parsed_url.path.lstrip("/").split("/")[0][:1] == "@") else False,
                "result": lambda parsed_url: "youtube.com/@" + parsed_url.path.lstrip("/").split("/")[0].lstrip("@")
            },
            {
                # Otherwise just remove scheme
                "rule": lambda parsed_url: True,
                "result": lambda parsed_url: urlunparse(ConsolidateURLs.remove_url_components(parsed_url,
                                                                                   remove_scheme=True,
                                                                                   )).lstrip("/")
            }
        ],
        "youtu.be": [
            {
                # TODO verify there are not other uses of youtu.be!
                "rule": lambda parsed_url: True,
                "result": lambda parsed_url: "youtube.com/watch?v=" + parsed_url.path.lstrip("/")
            }
        ]
    }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Update "columns" option with parent dataset columns
        """
        options = cls.options
        # Get the columns for the select columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["column"]["type"] = UserInput.OPTION_CHOICE
            options["column"]["options"] = {v: v for v in columns}
            options["column"]["default"] = "4CAT_extracted_urls" if "4CAT_extracted_urls" in columns else sorted(columns,
                                                                                    key=lambda k: any([name in k for name in ["url", "urls", "link"]])).pop()

        return options

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        This is meant to be inherited by other child classes

        :param module: Module to determine compatibility with
        """
        return module.get_extension() in ["csv", "ndjson"]

    def process(self):
        method = self.parameters.get("method", False)
        column = self.parameters.get("column", False)
        if not method or not column:
            self.dataset.update_status("Invalid parameters; ensure column and method are correct", is_final=True)
            self.dataset.finish(0)
            return
        expand_urls = self.parameters.get("expand_urls", False)

        # Get fieldnames
        fieldnames = self.source_dataset.get_item_keys(self) + ["4CAT_consolidated_urls_"+method]
        # Avoid requesting the same URL multiple times (if redirects are to be resolved)
        redirect_cache = {}

        # write a new file with the updated links
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()

            processed_items = 0
            total_items = self.source_dataset.num_rows
            progress_interval_size = max(int(total_items / 10), 1)  # 1/10 of total number of records
            for item in self.source_dataset.iterate_items(self):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while iterating through items")

                row = item.copy()
                value = item.get(column)
                consolidated_urls = []
                if value:
                    row_urls = value.split(",")
                    # Expand url shorteners
                    if expand_urls:
                        row_urls = [
                            ExtractURLs.resolve_redirect(url=url, redirect_domains=ExtractURLs.redirect_domains, cache=redirect_cache) for url in
                            row_urls]

                    # Consolidate URLs
                    for url in row_urls:
                        parsed_url = urlparse(url)

                        # Remove some common domain prefaces
                        split_domain = parsed_url.netloc.split(".")
                        domain = ".".join(split_domain[1:]) if split_domain[0] in self.domain_prefaces else ".".join(
                            split_domain)
                        parsed_url = parsed_url._replace(netloc=domain)

                        if method == 'domain':
                            consolidated_urls.append(domain)
                            continue

                        if method == "social_media":
                            if domain in self.social_media_rules:
                                for rule in self.social_media_rules[domain]:
                                    if rule["rule"](parsed_url):
                                        # Rule matched, append result and stop checking rules
                                        consolidated_urls.append(rule["result"](parsed_url))
                                        break
                            else:
                                # Return only the domain if no other rules exist
                                consolidated_urls.append(domain)
                                continue
                        else:
                            # Return URL with scheme, query, fragment removed and netloc modified
                            parsed_url = self.remove_url_components(
                                parsed_url,
                                remove_domain=False,  # replaced above
                                remove_scheme=self.parameters.get("remove_scheme", False),
                                remove_path=self.parameters.get("remove_path", False),
                                remove_query=self.parameters.get("remove_query", False),
                                remove_params=self.parameters.get("remove_parameters", False),
                                remove_fragment=self.parameters.get("remove_fragments", False),
                            )

                            consolidated_urls.append(urlunparse(parsed_url).lstrip("/"))

                row["4CAT_consolidated_urls_"+method] = ",".join(set(consolidated_urls))
                writer.writerow(row)
                processed_items += 1

                if processed_items % progress_interval_size == 0:
                    self.dataset.update_status(f"Processed {processed_items}/{total_items} items")
                    self.dataset.update_progress(processed_items / total_items)

        if redirect_cache:
            self.dataset.log(f"Expanded {len(redirect_cache)} URLs in dataset")
        self.dataset.finish(processed_items)

    @staticmethod
    def remove_url_components(parsed_url, remove_scheme=False, remove_domain=False, remove_path=False, remove_query=False, remove_params=False, remove_fragment=False):
        if remove_scheme:
            parsed_url = parsed_url._replace(scheme="")
        if remove_domain:
            parsed_url = parsed_url._replace(netloc="")
        if remove_path:
            parsed_url = parsed_url._replace(path="")
        if remove_query:
            parsed_url = parsed_url._replace(query="")
        if remove_params:
            parsed_url = parsed_url._replace(params="")
        if remove_fragment:
            parsed_url = parsed_url._replace(fragment="")

        return parsed_url

    @staticmethod
    def create_query_dictionary(url_query_string):
        return {query.split("=")[0]: (query.split("=")[1] if len(query.split("=")) == 2 else "") for query in url_query_string.split("&")}
