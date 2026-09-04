"""
Sample TikTok posts for a short time span by generating and requesting candidate post IDs

TikTok creates post IDs with a Snowflake-like scheme: the first 32 bits of the
64-bit ID are a UNIX timestamp in seconds, the next 10 bits are the millisecond
within that second, and the remaining 22 bits ('the tail') encode a counter, the
type of entity the ID belongs to, and the ID of the machine to which a post/video was uploaded.
Only a small number of tail IDs is ever used in practice, so if you know which tails
occur, you can enumerate nearly every ID that TikTok could possibly have used in a
given time range, and simply request them all--which is costly! The hit rate is under one percent,
so collecting even a few seconds of TikTok takes hundreds of thousands of requests.
This implements the method described in Steel et al. (2026).

"""
import json
import time
import re

import psycopg2

from datetime import datetime, timezone

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_datetime

from backend.lib.search import Search
from backend.lib.proxied_requests import FailedProxiedRequest
from common.lib.helpers import UserInput, convert_to_int, timify, andify
from common.lib.exceptions import (QueryParametersException, QueryNeedsExplicitConfirmationException,
                                   ProcessorInterruptedException)
from datasources.tiktok.search_tiktok import SearchTikTok
from datasources.tiktok_urls.search_tiktok_urls import TikTokScraper

# Bit layout of a TikTok post ID, as determined by Steel et al. (2026). Bit 0 is
# the most significant bit of the 64-bit integer.
ID_LENGTH = 64
TIMESTAMP_SLICE = (0, 32)  # UNIX timestamp, in seconds
MILLISECOND_SLICE = (32, 42)  # millisecond within that second (0-999)
TAIL_SLICE = (42, 64)  # counter, entity type and machine ID
TAIL_LENGTH = TAIL_SLICE[1] - TAIL_SLICE[0]

# offsets within the 22-bit tail
TAIL_TYPE_SLICE = (10, 14)  # ID bits 52-55; the entity type
TAIL_MACHINE_SLICE = (16, 22)  # ID bits 58-63; the machine (datacentre) ID
MACHINE_ID_LENGTH = TAIL_MACHINE_SLICE[1] - TAIL_MACHINE_SLICE[0]
VIDEO_ENTITY_TYPE = 13  # 0xd - the entity type of a video post

# any username resolves, as long as the ID after it exists
DUMMY_USERNAME = "fourcat"

# data source types whose result files contain TikTok post IDs we can seed
SEEDED_TYPES = ("tiktok-search", "tiktok-urls-search", "tiktok-sample-search")

# where the seeded tails are cached between queries, by the seeding worker in
# seed_tiktok_sample.py. the version is bumped when the file gains something the
# data source needs; older files are still read for what they do contain
TAIL_CACHE_FILE = "tiktok-sample-tails.json"
CACHE_VERSION = 3

# how often the seeding worker re-reads the datasets on this server, in seconds
SEED_INTERVAL = 86400

# how many countries to name per machine ID in the query form. a machine mints
# posts from all over, so listing every country it ever saw would be unreadable
# and would suggest more precision than there is
MACHINE_LOCATION_LIMIT = 5

# how far the 'n most common machine IDs' dropdown goes
MAX_COMMON_MACHINES = 50

# coverage targets offered for limiting the ID patterns, most complete first.
# a ladder rather than a free number, because everything interesting happens in
# the last few percent: on a well-seeded instance the step from 100% to 99%
# roughly halves the cost, and the steps below 98% start dropping whole machine
# IDs rather than rare patterns, which biases a sample geographically
PATTERN_COVERAGE_TARGETS = (100, 99.9, 99.5, 99, 98, 95, 90, 80)
MAX_PATTERN_OPTIONS = 25

# longest time range that may be sampled, in seconds
MAX_DURATION = 10

# what to tell someone who has no ID patterns and no way to come by them. The
# data source simply cannot run in that state, so it says so rather than
# generating IDs that are certain not to exist
ASK_FOR_PATTERNS = ("Ask an administrator to fill in the 'Known TikTok ID patterns' setting for this data source, or "
                    "import a TikTok dataset on this server so that patterns can be read from it.")
NO_PATTERNS_ANYWHERE = ("This 4CAT instance has no TikTok ID patterns to sample with: none are configured, and there "
                        "are no TikTok datasets on this server to derive them from. " + ASK_FOR_PATTERNS)

# and to someone who is only early. the seeding worker runs on startup and then
# daily, so this state resolves itself
NOT_SEEDED_YET = ("4CAT reads TikTok ID patterns from the TikTok datasets on this server once a day, and that has not "
                  "produced any patterns yet on this instance. If there are TikTok datasets here, try again later. "
                  + ASK_FOR_PATTERNS)

# how many candidate IDs may come back empty before we say something is wrong.
# at the ~1/125 rate Steel et al. report, seeing nothing in this many requests
# has a probability of well under a percent
ZERO_HIT_WARNING_AFTER = 2000


class SearchTikTokSample(Search):
    """
    Sample TikTok posts by generating candidate post IDs
    """
    type = "tiktok-sample-search"  # job ID
    category = "Search"  # category
    title = "Sample TikTok posts by ID"  # title displayed in UI
    description = ("Collect a sample of TikTok videos made during a short time range by generating "
                   "every plausible post ID for that range and requesting them all.")  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    # not available as a processor for existing datasets
    accepts = [None]

    references = [
        "Steel, B.D., Schirmer, M., Ruths, D., & Pfeffer, J. (2026). Just Another Hour on TikTok: ID sampling to "
        "obtain a complete slice of TikTok. *Journal of Quantitative Description*, 6. "
        "[https://journalqd.org/article/view/9514](https://journalqd.org/article/view/9514)"
    ]

    config = {
        "tiktok-sample-search.id-patterns": {
            "type": UserInput.OPTION_TEXT_LARGE,
            "default": "",
            "help": "Known TikTok ID patterns",
            "tooltip": "One pattern per line. A pattern may be written as 22 binary digits, as a number between "
                       "0 and 4194303, as 64 binary digits, or as a full TikTok post ID (in the latter two cases the "
                       "last 22 bits are used). If this is left empty, 4CAT seeds patterns from the TikTok "
                       "datasets on this server instead."
        },
        "tiktok-sample-search.seed-limit": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 250_000,
            "min": 1_000,
            "help": "Post IDs to seed",
            "tooltip": "How many unique post IDs to read from existing datasets before deciding that enough ID "
                       "patterns have been found. Steel et al. used 225,000 posts to reach an estimated 99.97% "
                       "coverage. This is only used if no ID patterns are inserted above."
        },
        "tiktok-sample-search.max-candidates": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 1_000_000,
            "min": 1,
            "help": "Maximum candidate IDs per query",
            "tooltip": "Each candidate ID costs one request to TikTok, and fewer than one in a hundred yields a post, "
                       "so raise this only if this 4CAT instance has the proxies to support it."
        }
    }

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get data source options

        The available ID patterns determine how large a time range can be
        sampled, so they are reported here as well.

        :param DataSet parent_dataset:  An object representing the dataset that
            the processor would be or was run on and can be used to show some options
            only to privileged users.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        """
        known_tails, tail_source, tail_problem = cls.get_known_tails(config)
        max_candidates = convert_to_int(config.get("tiktok-sample-search.max-candidates", 1_000_000), 1_000_000) \
            if config else 1000000

        if known_tails:
            patterns_info = (f"**{len(known_tails):,} ID patterns** are currently known to this 4CAT instance "
                             f"({tail_source}). At that number, sampling one full second of TikTok costs "
                             f"{len(known_tails) * 1000:,} requests, so the settings below need to keep the total "
                             f"below {max_candidates:,}.")
            if tail_problem:
                patterns_info += f"\n\n{tail_problem}"
        elif tail_problem:
            patterns_info = f"**No usable ID patterns.** {tail_problem}"
        elif cls.count_seedable_datasets(config) == 0:
            patterns_info = f"**This data source cannot run yet.** {NO_PATTERNS_ANYWHERE}"
        else:
            patterns_info = ("**No ID patterns are known to this 4CAT instance yet, so no sample can be made.** 4CAT "
                             "reads the post IDs of the TikTok datasets on this server to find them, once when it "
                             "starts and daily after that, so try again later. If there are no TikTok datasets here, "
                             "you either need to import a large dataset of TikTok videos (via Zeeschuimer) or an "
                             "administrator will need to configure a list of patterns. Note that TikTok's "
                             "infrastructure changes over time, so lists may expire.")

        return {
            "intro": {
                "type": UserInput.OPTION_INFO,
                "help": "This data source collects a sample of everything posted to TikTok during a "
                        "very short time range, using the method of [Steel et al. "
                        "(2026)](https://journalqd.org/article/view/9514). It works out every ID "
                        "TikTok could have generated between two points in time and requests each one.\n\nThis is slow: "
                        " fewer than one in a hundred candidate IDs corresponds to a post that ever "
                        "existed, and fewer still to one that can still be retrieved, so expect a few thousand posts "
                        "per million requests. This can be sped up if proxies are configured. "
                        "Steel et al. needed five months to collect 83 minutes of TikTok."
            },
            "patterns-info": {
                "type": UserInput.OPTION_INFO,
                "help": patterns_info
            },
            "range-divider": {
                "type": UserInput.OPTION_DIVIDER
            },
            "start_time": {
                "type": UserInput.OPTION_TEXT,
                "help": "Start of range (UTC)",
                "tooltip": "Use a UNIX timestamp or YYYY-MM-DD HH:MM:SS. Always read as UTC. This is the time encoded "
                           "in the post ID, which does not always correspond to creation or upload time (see Steel et "
                           "al. 2026)."
            },
            "duration": {
                "type": UserInput.OPTION_TEXT,
                "coerce_type": int,
                "default": 1,
                "min": 1,
                "max": MAX_DURATION,
                "help": "Duration (seconds)",
                "tooltip": f"How many seconds to sample, starting at the time above. At most {MAX_DURATION}."
            },
            "milliseconds": {
                "type": UserInput.OPTION_TEXT,
                "coerce_type": int,
                "default": 1000,
                "min": 1,
                "max": 1000,
                "help": "Sample by first n milliseconds",
                "tooltip": "Only sample the first this many milliseconds of each second. Steel et al. found the "
                           "millisecond field to be uniformly distributed, so lowering this yields a random "
                           "subsample of the posts in the second. This can be used for a longer time range at the "
                           "expense of completeness."
            },
            **cls.get_machine_options(known_tails, cls.get_machines(config)),
            **cls.get_pattern_limit_option(known_tails),
        }

    @classmethod
    def get_pattern_limit_option(cls, tails):
        """
        The control for leaving out the rarest ID patterns

        :param dict tails:  Patterns mapped to how often they occurred
        :return dict:  Data source options
        """
        options = cls.get_pattern_options(tails)
        if len(options) < 2:
            # nothing to choose between: either there are no patterns, or too
            # few for any target to leave a different number of them
            return {}

        return {
            "pattern-divider": {
                "type": UserInput.OPTION_DIVIDER
            },
            "pattern_coverage": {
                "type": UserInput.OPTION_CHOICE,
                "default": "100",
                "options": options,
                "help": "Limit by most common ID patterns",
                "tooltip": "Patterns are ranked by how often they occurred in the TikTok data on this server. Every "
                           "pattern costs the same number of requests per second sampled, but the rarest ones almost "
                           "never yield a post, so leaving them out raises the share of requests that find something "
                           "- the hit rate - and shortens the query. What it costs is coverage: the percentage is how "
                           "much of the known posting each option still reaches, and the posts it gives up are the "
                           "ones made through the rarest patterns, which is not a random subset. Below roughly 98% "
                           "whole machine IDs start dropping out, which skews the sample towards particular regions. "
                           "The pattern counts above are for all machine IDs. If you also limit machine IDs, the same "
                           "percentage is taken of what those machines posted, so it uses proportionally fewer "
                           "patterns than the count shown - the two limits multiply rather than compete."
            }
        }

    @classmethod
    def get_machine_options(cls, tails, machines):
        """
        Build the controls for choosing which machine IDs to sample with

        A machine ID identifies the datacentre a post was uploaded to, and
        which of them a post ends up on correlates with where it was made. The
        correlation is loose, so rather than presenting machine IDs as a
        region filter, the countries observed for each machine are shown as
        they are, and someone can decide from those what to sample.

        Which controls are offered depends on what this 4CAT instance knows:
        without patterns there is nothing to choose from, and without seeded
        location data (because none was collected yet, or because the patterns
        come from a list an administrator configured) there is nothing to
        select a location by.

        :param dict tails:  Patterns mapped to how often they occurred
        :param dict machines:  Machine IDs mapped to their post and location
          counts, as returned by `get_machines()`
        :return dict:  Data source options
        """
        if not tails:
            return {}

        ranked = cls.rank_machines(tails)
        located = {machine: data for machine, data in machines.items() if data.get("locations")}
        modes = {"all": f"Use all {len(ranked)} known machine ID(s)"}

        if located:
            modes["location"] = "Select by location"

        if len(ranked) > 1:
            # with one machine ID, 'the most common one' is simply all of them
            modes["common"] = "Use only the most common machine IDs"

        modes["custom"] = "Use a custom list of machine IDs"

        options = {
            "machine-divider": {
                "type": UserInput.OPTION_DIVIDER
            },
            "machine_id_mode": {
                "type": UserInput.OPTION_CHOICE,
                "default": "all",
                "options": modes,
                "help": "Machine IDs",
                "tooltip": "The last six bits of a post ID identify the datacentre the post was uploaded to. Limiting "
                           "which of them are sampled makes a query cheaper, at the cost of no longer sampling the "
                           "whole platform."
            },
            "machine_id_info_all": {
                "type": UserInput.OPTION_INFO,
                "requires": "machine_id_mode==all",
                "help": f"All {len(ranked)} machine ID(s) known to this 4CAT instance are sampled. This is the only "
                        f"setting that samples TikTok as a whole; every other one trades coverage for a smaller query."
            }
        }

        if located:
            breakdown = "\n".join(
                f"- **{machine}**: {data['located']:,} of {data['posts']:,} post(s) named a country — "
                f"{cls.describe_locations(data['locations'])}"
                for machine, data in sorted(
                    located.items(), key=lambda item: (-item[1]["posts"], item[0])
                )
            )

            # most TikTok posts do not carry a location at all, so say what the
            # shares below are actually a share of before anyone reads them as
            # 'this machine is 62% American'
            total_posts = sum(data["posts"] for data in machines.values())
            total_located = sum(data["located"] for data in machines.values())
            located_share = total_located / total_posts if total_posts else 0

            options["machine_id_info_location"] = {
                "type": UserInput.OPTION_INFO,
                "requires": "machine_id_mode==location",
                "help": f"Selecting a location uses every machine ID that has that country among the "
                        f"{MACHINE_LOCATION_LIMIT} countries listed for it below. Machines mint posts from all over, "
                        f"so this narrows a sample towards a region rather than restricting it to one, and the "
                        f"resulting dataset will contain posts from elsewhere. The shares below are of the posts this "
                        f"4CAT instance happens to have seen, which is not a sample of TikTok.\n\n"
                        f"**Most TikTok posts do not say where they were made.** Of the {total_posts:,} post(s) read "
                        f"here, {total_located:,} ({located_share:.0%}) named a country, and everything below is a "
                        f"share of those alone. A machine ID that mostly posts nothing at all can still end up listed "
                        f"under a country on the strength of the few posts that did say something, so treat a thin "
                        f"row below as the weak evidence it is.\n\n{breakdown}"
            }
            options["machine_id_locations"] = {
                "type": UserInput.OPTION_MULTI_SELECT,
                "default": [],
                "options": cls.get_location_options(located),
                "requires": "machine_id_mode==location",
                "help": "Locations",
                "tooltip": "Country the post said it was created in, as recorded in the posts this 4CAT instance has "
                           "collected."
            }

        if "common" in modes:
            options["machine_id_info_common"] = {
                "type": UserInput.OPTION_INFO,
                "requires": "machine_id_mode==common",
                "help": "Machine IDs are ranked by how many of the known posts they minted. Each option below says "
                        "what share of those posts it accounts for, and which countries were seen for it, so a set "
                        "can be picked for what it covers as well as for how much it costs."
            }
            options["machine_id_count"] = {
                "type": UserInput.OPTION_CHOICE,
                "default": "0",
                "options": cls.get_common_machine_options(tails, machines),
                "requires": "machine_id_mode==common",
                "help": "Most common machine IDs"
            }

        options["machine_id_info_custom"] = {
            "type": UserInput.OPTION_INFO,
            "requires": "machine_id_mode==custom",
            "help": f"One machine ID per line, or separated by commas. A machine ID may be written as "
                    f"{MACHINE_ID_LENGTH} binary digits (`000101`) or as the number those digits represent (`5`), "
                    f"which is what the `machine_id_bits` and `machine_id` columns of a TikTok dataset contain. IDs "
                    f"that are not known to this 4CAT instance simply match no patterns.\n\nKnown machine IDs: "
                    + ", ".join(f"`{machine}`" for machine in ranked)
        }
        options["machine_id_custom"] = {
            "type": UserInput.OPTION_TEXT_LARGE,
            "default": "",
            "requires": "machine_id_mode==custom",
            "help": "Machine IDs"
        }

        return options

    @classmethod
    def get_location_options(cls, machines):
        """
        List the countries that can be sampled by

        Only countries a machine is actually associated with are listed, i.e.
        the ones named for it in the query form - anything further down the
        tail of a machine's location counts would be a country someone could
        select without it selecting anything they were shown.

        :param dict machines:  Machine IDs mapped to their post and location
          counts
        :return dict:  Country codes mapped to a label
        """
        posts = {}
        machines_per_country = {}

        for machine, data in machines.items():
            for code in cls.machine_locations(data):
                machines_per_country[code] = machines_per_country.get(code, 0) + 1

            for code, count in data["locations"].items():
                posts[code] = posts.get(code, 0) + count

        total = sum(posts[code] for code in machines_per_country)
        options = {}

        for code in sorted(machines_per_country, key=lambda code: (-posts[code], code)):
            share = posts[code] / total if total else 0
            options[code] = (f"{code}: {'<1%' if share < 0.005 else format(share, '.0%')} of located posts, "
                             f"{machines_per_country[code]} machine ID(s)")

        return options

    @classmethod
    def get_common_machine_options(cls, tails, machines):
        """
        Build the 'n most common machine IDs' dropdown

        There is one option per machine ID this 4CAT instance actually knows
        about, and no more: selecting every machine is what 'all' already does.

        Each option says what share of the known posts those machines minted,
        and which countries were seen for them, so that what a narrower sample
        gives up is visible at the point where it is chosen. The share is what
        distinguishes the options on an instance where every machine posts from
        the same handful of countries.

        :param dict tails:  Patterns mapped to how often they occurred
        :param dict machines:  Machine IDs mapped to their post and location
          counts; may be empty
        :return dict:  Option values mapped to a label
        """
        counted = cls.count_machines(tails)
        ranked = sorted(counted, key=lambda machine: (-counted[machine], machine))
        total = sum(counted.values())

        options = {"0": f"All {len(ranked)} machine ID(s)"}
        combined = {}
        covered = 0

        for amount, machine in enumerate(ranked[:min(MAX_COMMON_MACHINES, len(ranked) - 1)], start=1):
            covered += counted[machine]
            for code, count in machines.get(machine, {}).get("locations", {}).items():
                combined[code] = combined.get(code, 0) + count

            share = covered / total if total else 0
            options[str(amount)] = f"{amount} — {'<1%' if share < 0.005 else format(share, '.0%')} of known posts" \
                                   + (f"; {cls.describe_locations(combined)}" if combined else "")

        return options

    @staticmethod
    def validate_query(query, request, config):
        """
        Validate TikTok sample query

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:  Safe query parameters
        """
        start_time = str(query.get("start_time", "")).strip()
        if not start_time:
            raise QueryParametersException("You need to provide a start time for the range to sample.")

        try:
            if start_time.isdigit() and len(start_time) >= 9:
                # a UNIX timestamp, e.g. because this query is being re-run from
                # the parameters of an earlier dataset
                start = datetime.fromtimestamp(int(start_time), tz=timezone.utc)
            else:
                start = parse_datetime(start_time)
        except (ValueError, TypeError, OverflowError, OSError):
            raise QueryParametersException(f"'{start_time}' could not be read as a date and time. Use a UNIX timestamp "
                                           f"or text string like 2024-04-10 17:00:00.")

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        start = int(start.timestamp())
        duration = max(1, min(MAX_DURATION, convert_to_int(query.get("duration"), 1)))
        milliseconds = max(1, min(1000, convert_to_int(query.get("milliseconds"), 1000)))

        machine_query = {
            "machine_id_mode": query.get("machine_id_mode", "all"),
            "machine_id_locations": query.get("machine_id_locations", []),
            "machine_id_count": max(0, convert_to_int(query.get("machine_id_count"), 0)),
            "machine_id_custom": str(query.get("machine_id_custom", "")).strip()
        }

        if machine_query["machine_id_mode"] not in ("all", "location", "common", "custom"):
            machine_query["machine_id_mode"] = "all"

        if machine_query["machine_id_mode"] == "custom":
            # the machine IDs are checked here rather than at run time because a
            # typo in this list is otherwise indistinguishable from a machine
            # that happens to have no patterns
            custom, rejected = SearchTikTokSample.parse_machine_ids(machine_query["machine_id_custom"])
            if rejected:
                raise QueryParametersException(
                    f"These entries in the custom machine ID list could not be read: {', '.join(rejected[:10])}. Write "
                    f"each machine ID as {MACHINE_ID_LENGTH} binary digits (e.g. 000101) or as the number those "
                    f"digits represent (0-{2 ** MACHINE_ID_LENGTH - 1}).")
            elif not custom:
                raise QueryParametersException("You need to provide at least one machine ID to sample with.")

        elif machine_query["machine_id_mode"] == "location" and not machine_query["machine_id_locations"]:
            raise QueryParametersException("You need to select at least one location to sample with.")

        now = int(datetime.now(tz=timezone.utc).timestamp())
        if start < 1474329600:
            raise QueryParametersException("The start of the range must be after 20 September 2016.")
        elif start + duration > now:
            raise QueryParametersException("The range to sample must lie fully in the past.")

        # figure out how many candidate IDs this would generate. seeding happens
        # in the background rather than as part of a query, so without patterns
        # there is nothing to sample with and no point in queueing anything
        known_tails, _, tail_problem = SearchTikTokSample.get_known_tails(config)
        if not known_tails and tail_problem:
            raise QueryParametersException(tail_problem)
        elif not known_tails and SearchTikTokSample.count_seedable_datasets(config) == 0:
            # nothing configured, nothing cached and nothing to seed from, so
            # this query could only ever request IDs that cannot exist
            raise QueryParametersException(NO_PATTERNS_ANYWHERE)
        elif not known_tails:
            raise QueryParametersException(NOT_SEEDED_YET)

        machines, machine_problem = SearchTikTokSample.resolve_machines(
            machine_query, known_tails, SearchTikTokSample.get_machines(config))

        coverage = SearchTikTokSample.parse_coverage(query.get("pattern_coverage"))
        tail_count = len(SearchTikTokSample.select_tails(known_tails, machines=machines, coverage=coverage))
        if not tail_count:
            raise QueryParametersException("The chosen limits on ID patterns and machine IDs leave no patterns to "
                                           "sample with." + (f" {machine_problem}" if machine_problem else ""))

        candidates = duration * milliseconds * tail_count
        max_candidates = convert_to_int(config.get("tiktok-sample-search.max-candidates", 1_000_000), 1_000_000)

        if candidates > max_candidates:
            raise QueryParametersException(
                f"This query would generate {candidates:,} candidate IDs, more than the {max_candidates:,} this 4CAT "
                f"instance allows. Sample fewer seconds, fewer milliseconds per second, or fewer ID patterns. With "
                f"{tail_count:,} patterns you can sample {max(1, max_candidates // (tail_count * milliseconds))} "
                f"second(s) at {milliseconds} milliseconds each.")

        # a very rough estimate of how long this will take, from the number of
        # proxies available and how long they have to cool off between requests
        proxies = config.get("proxies.urls", ["__localhost__"]) or ["__localhost__"]
        cooloff = float(config.get("proxies.cooloff", 0.1) or 0.1)
        concurrent = max(1, convert_to_int(config.get("proxies.concurrent-host", 1), 1))
        rate = max(len(proxies) * concurrent / (cooloff + 1.0), 0.01)
        expected_time = candidates / rate

        if expected_time > 3600 and not query.get("frontend-confirm"):
            raise QueryNeedsExplicitConfirmationException(
                f"This query requests {candidates:,} URLs from TikTok, which with the {len(proxies)} proxy/proxies "
                f"configured for this 4CAT instance may take around {timify(expected_time)}. Do you want to continue?")

        return {
            "start_time": start,
            "duration": duration,
            "milliseconds": milliseconds,
            "pattern_coverage": coverage,
            **machine_query
        }

    @staticmethod
    def parse_coverage(value):
        """
        Read a coverage target

        :param value:  Value from the query form or from dataset parameters
        :return float:  A percentage between 0 and 100; 100 if unreadable
        """
        try:
            return min(100.0, max(0.0, float(value)))
        except (TypeError, ValueError):
            return 100.0

    def get_items(self, query):
        """
        Generate candidate TikTok post IDs and request them all

        :param dict query:  Search query parameters
        """
        tails, source, tail_problem = self.get_known_tails(self.config)
        if not tails:
            self.dataset.finish_with_error(tail_problem or NOT_SEEDED_YET)
            return

        self.dataset.log(f"Using {len(tails):,} ID patterns ({source}).")
        if tail_problem:
            self.dataset.log(tail_problem)

        # the patterns are re-seeded daily, so which machine IDs a query's
        # settings resolve to can have changed since it was submitted
        machine_data = self.get_machines(self.config)
        machines, machine_problem = self.resolve_machines(query, tails, machine_data)
        if machine_problem:
            self.dataset.log(machine_problem)

        coverage = self.parse_coverage(query.get("pattern_coverage"))
        selected = self.select_tails(tails, machines=machines, coverage=coverage)
        if not selected:
            self.dataset.finish_with_error(("The chosen limits on ID patterns and machine IDs leave no patterns to "
                                            "sample with. " + machine_problem).strip())
            return

        # the number of patterns may have changed since the query was validated
        # (e.g. because they had not been seeded yet), so check the budget
        # again and drop the rarest patterns if it no longer fits
        max_candidates = convert_to_int(self.config.get("tiktok-sample-search.max-candidates", 1_000_000),
                                        1_000_000)
        per_pattern = query["duration"] * query["milliseconds"]
        if len(selected) * per_pattern > max_candidates:
            fits = max_candidates // per_pattern
            if not fits:
                self.dataset.finish_with_error(
                    f"Even a single ID pattern needs {per_pattern:,} requests for this range, more than the "
                    f"{max_candidates:,} this 4CAT instance allows. Sample a shorter range.")
                return

            self.dataset.update_status(
                f"{len(selected):,} ID patterns would need {len(selected) * per_pattern:,} requests; using only the "
                f"{fits:,} most common patterns to stay within this instance's limit of {max_candidates:,}. Coverage "
                f"of this time range will be lower than it could be.")
            selected = selected[:fits]

        candidates = len(selected) * per_pattern
        used_machines = sorted({int(tail[TAIL_MACHINE_SLICE[0]:TAIL_MACHINE_SLICE[1]], 2) for tail in selected})
        start_readable = datetime.fromtimestamp(query["start_time"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # record exactly what was sampled, so the dataset can be reproduced
        self.dataset.log(f"Sampling {query['duration']} second(s) from {start_readable} UTC "
                         f"(timestamps {query['start_time']} to {query['start_time'] + query['duration'] - 1}).")
        self.dataset.log(f"Sampling milliseconds 0 to {query['milliseconds'] - 1} of each second.")
        self.dataset.log(f"Machine ID selection: {query.get('machine_id_mode', 'all')}.")
        if coverage < 100:
            # the denominator is the patterns left after the machine ID limits,
            # not every pattern known here, since that is what the coverage
            # target was applied to
            available = len(self.select_tails(tails, machines=machines))
            scope = "the selected machine IDs" if machines is not None else "this 4CAT instance"
            self.dataset.log(f"Limited to the most common ID patterns covering {coverage:g}% of the posts known here "
                             f"for {scope}: {len(selected):,} of {available:,} pattern(s). Posts made through the "
                             f"patterns left out are not sampled.")
        self.dataset.log(f"Using {len(selected):,} ID pattern(s) covering {len(used_machines)} machine ID(s), with "
                         f"the locations recorded for them:")
        for machine in used_machines:
            self.dataset.log(f"  {machine}: {self.describe_locations(machine_data.get(machine, {}).get('locations', {}))}")
        self.dataset.log("ID patterns used (bits 42-63 of the post ID):\n" + "\n".join(selected))

        self.dataset.update_status(f"Requesting {candidates:,} candidate TikTok post IDs")

        scraper = TikTokScraper(processor=self, config=self.config)
        urls = self.candidate_urls(query["start_time"], query["duration"], query["milliseconds"], selected)

        requested = 0
        collected = 0
        outcomes = {}
        interrupted = False
        warned = False
        started = time.time()

        for url, response in self.iterate_proxied_requests(urls, preserve_order=False,
                                                           headers=TikTokScraper.headers, timeout=30):
            if self.interrupted:
                # a cancelled dataset should go away; an interrupted one would
                # have to start this whole thing over, so keep what we have
                if self.interrupted == self.INTERRUPT_CANCEL:
                    raise ProcessorInterruptedException("Interrupted while sampling TikTok posts")

                self.flush_proxied_requests()
                interrupted = True
                break

            requested += 1

            for outcome, video in self.interpret_response(response, scraper):
                if video is not None:
                    collected += 1
                    yield video

                outcomes[outcome] = outcomes.get(outcome, 0) + 1

            # at the rates Steel et al. report, a run this long without a single
            # hit means the ID patterns do not match what TikTok is minting -
            # say so now rather than after another hundred thousand requests
            if not collected and not warned and requested >= ZERO_HIT_WARNING_AFTER:
                warned = True
                self.dataset.log(
                    f"No posts found in the first {requested:,} candidate IDs. Steel et al. report that roughly one "
                    f"in 125 candidate IDs has ever existed, so some hits would be expected by now. The ID patterns "
                    f"in use most likely do not match the IDs TikTok currently mints: check that they were derived "
                    f"from video post IDs, using bits 42-63 of the 64-bit ID.")

            if requested == 1 or requested % 50 == 0:
                # the rate so far, carried forward. proxies come and go and
                # TikTok's own pace varies, so this is an order of magnitude
                # rather than an estimate
                elapsed = time.time() - started
                left = f", about {timify(elapsed / requested * (candidates - requested))} left" \
                    if elapsed > 10 and requested < candidates else ""

                self.dataset.update_status(f"Requested {requested:,} of {candidates:,} candidate IDs, found "
                                           f"{collected:,} post(s){left}"
                                           + (" - no hits yet, see the dataset log" if warned else ""))
                self.dataset.update_progress(requested / candidates)

        # the breakdown of what TikTok said about the IDs that did not yield a
        # post is what lets you estimate how many posts existed in this range,
        # so report it rather than just the hits
        self.dataset.log(f"Requested {requested:,} candidate IDs and collected {collected:,} post(s). Outcomes:")
        for outcome, count in sorted(outcomes.items(), key=lambda item: -item[1]):
            self.dataset.log(f"  {outcome}: {count:,} ({count / max(requested, 1):.4%})")

        if interrupted:
            self.dataset.update_status(
                f"Interrupted after {requested:,} of {candidates:,} candidate IDs. The {collected:,} post(s) found so "
                f"far were kept, but this is not a complete sample of the time range.", is_final=True)

    def interpret_response(self, response, scraper):
        """
        Work out what TikTok's answer for a candidate ID means

        Yields one tuple per outcome: a short description of what happened, and
        the post metadata if there was any. Most candidate IDs never belonged to
        a post, so most of the time the metadata is `None`.

        :param response:  Response for the request, or a FailedProxiedRequest
        :param TikTokScraper scraper:  Scraper to reformat metadata with
        :return:  Yields tuples of an outcome description and post metadata
        """
        if isinstance(response, FailedProxiedRequest):
            yield "request failed", None
            return

        if response.status_code == 404:
            yield "no such post (HTTP 404)", None
            return
        elif response.status_code != 200:
            yield f"unexpected HTTP response ({response.status_code})", None
            return

        soup = BeautifulSoup(response.text, "html.parser")
        sigil = soup.select_one("script#__UNIVERSAL_DATA_FOR_REHYDRATION__")
        if not sigil:
            sigil = soup.select_one("script#SIGI_STATE")

        if not sigil:
            yield "no embedded metadata in page", None
            return

        try:
            raw = sigil.text if sigil.text else (sigil.contents[0] if sigil.contents else "")
            metadata = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            yield "embedded metadata could not be parsed", None
            return

        # TikTok reports why an ID does not resolve in the embedded JSON. We do
        # not interpret these messages - which of them mean 'this post existed
        # once' is not documented - but we do count them separately
        detail = metadata.get("__DEFAULT_SCOPE__", {}).get("webapp.video-detail", {})
        status = detail.get("statusMsg") or f"status code {detail.get('statusCode')}"

        found = False
        for video in scraper.reformat_metadata(metadata):
            found = True
            if video == scraper.VIDEO_NOT_FOUND:
                yield f"no post ({status})", None
            elif not video.get("stats") or video.get("createTime") == "0":
                # empty metadata usually means the post is behind a login wall
                yield "post exists but requires logging in", None
            else:
                yield "post collected", video

        if not found:
            yield "unrecognised response", None

    @staticmethod
    def candidate_urls(start, duration, milliseconds, tails):
        """
        Generate a URL for every candidate post ID in the given range

        Millisecond is the outer loop so that a run that is cut short still
        covers the whole time range evenly, instead of only its first seconds.

        :param int start:  First second of the range, as a UNIX timestamp
        :param int duration:  Number of seconds to cover
        :param int milliseconds:  Number of milliseconds to cover per second
        :param list tails:  ID patterns to use, as strings of 22 bits
        :return:  Yields TikTok post URLs
        """
        second_width = TIMESTAMP_SLICE[1] - TIMESTAMP_SLICE[0]
        millisecond_width = MILLISECOND_SLICE[1] - MILLISECOND_SLICE[0]

        for millisecond in range(milliseconds):
            millisecond_bits = f"{millisecond:0{millisecond_width}b}"
            for second in range(start, start + duration):
                prefix = f"{second:0{second_width}b}" + millisecond_bits
                for tail in tails:
                    post_id = int(prefix + tail, 2)
                    yield f"https://www.tiktok.com/@{DUMMY_USERNAME}/video/{post_id}"

    @staticmethod
    def count_seedable_datasets(config):
        """
        Count the TikTok datasets ID patterns could be seeded from

        Used to tell someone that a query cannot work *before* they wait for it
        to be picked up, rather than after.

        :param config:  Configuration reader
        :return int|None:  How many datasets there are, or `None` if that could
          not be established from here
        """
        try:
            counted = config.db.fetchone(
                "SELECT COUNT(*) AS num FROM datasets WHERE type IN %s AND is_finished = TRUE "
                "AND key_parent = ''", (SEEDED_TYPES,))
            return counted["num"] if counted else 0
        except (AttributeError, TypeError, KeyError, psycopg2.Error):
            # no database from this context, or the query failed; leave it to
            # the worker to find out rather than blocking a query wrongly
            return None

    @classmethod
    def get_known_tails(cls, config):
        """
        Get the ID patterns this 4CAT instance knows about

        Patterns configured by an administrator take precedence over patterns
        seeded from datasets on this server.

        :param ConfigManager|None config:  Configuration reader
        :return tuple:  A dictionary of patterns mapped to how often they
          occurred, a description of where they came from, and a description of
          anything wrong with the configured patterns (empty if all is well)
        """
        if not config:
            return {}, "", ""

        configured, rejected = cls.parse_tail_setting(config.get("tiktok-sample-search.id-patterns", "") or "")
        summary = ", ".join(f"{count:,} {reason}" for reason, count in sorted(rejected.items()))

        if configured:
            return configured, "configured by an administrator", \
                (f"Of the configured ID patterns, {summary}; those entries were ignored." if rejected else "")
        elif rejected:
            # falling back to seeded patterns here would hide the problem, and
            # an unusable list is worth an error rather than a silent fallback
            return {}, "", (
                f"The 'Known TikTok ID patterns' setting is filled in, but none of its entries can be used: "
                f"{summary}. A pattern is bits 42-63 of a video post's 64-bit ID, written as {TAIL_LENGTH} binary "
                f"digits with the leading zeros intact.")

        cache = cls.read_cache(config)
        tails = {tail: count for tail, count in cache.get("tails", {}).items() if len(tail) == TAIL_LENGTH}
        if not tails:
            return {}, "", ""

        seeded = datetime.fromtimestamp(cache.get("created", 0), tz=timezone.utc).strftime("%d %B %Y")
        return tails, (f"seeded from {cache.get('posts_scanned', 0):,} post IDs in "
                       f"{cache.get('datasets_scanned', 0):,} dataset(s) on this server on {seeded}"), ""

    @staticmethod
    def read_cache(config):
        """
        Read what the seeding worker last found

        :param ConfigManager|None config:  Configuration reader
        :return dict:  Cache contents, or an empty dictionary if there is no
          readable cache
        """
        if not config:
            return {}

        try:
            path = config.get("PATH_CONFIG").joinpath(TAIL_CACHE_FILE)
            if not path.exists():
                return {}

            with path.open(encoding="utf-8") as infile:
                cache = json.load(infile)

            return cache if type(cache) is dict else {}

        except (OSError, AttributeError, ValueError, json.JSONDecodeError):
            return {}

    @classmethod
    def get_machines(cls, config):
        """
        Get the machine IDs this 4CAT instance knows about, and where they post

        Only available for seeded patterns: a list configured by an
        administrator says nothing about where its patterns were seen, and
        pairing it with a location breakdown from a seeding run it has nothing
        to do with would be worse than having no breakdown at all.

        Every country a machine's posts named is kept here; the query form
        names only the most common few of them per machine, and it is those
        that a selection acts on, so that what someone picks is what they saw.

        :param ConfigManager|None config:  Configuration reader
        :return dict:  Machine IDs (as integers) mapped to dictionaries with a
          `posts` count, a `located` count of those posts that named a country,
          and a `locations` dictionary of country code counts
        """
        if not config:
            return {}

        configured, _ = cls.parse_tail_setting(config.get("tiktok-sample-search.id-patterns", "") or "")
        if configured:
            return {}

        machines = {}
        for machine, data in cls.read_cache(config).get("machines", {}).items():
            machine = convert_to_int(machine, -1)
            if not 0 <= machine < 2 ** MACHINE_ID_LENGTH or type(data) is not dict:
                continue

            # caches written before `located` was recorded still have the counts
            # it was the total of, so fall back to those
            located = convert_to_int(data.get("located", sum(data.get("locations", {}).values())), 0)

            locations = {code: count for code, count in data.get("locations", {}).items()
                         if type(code) is str and len(code) == 2}

            machines[machine] = {
                "posts": convert_to_int(data.get("posts"), 0),
                "located": located,
                "locations": locations
            }

        return machines

    @staticmethod
    def describe_locations(locations, limit=MACHINE_LOCATION_LIMIT):
        """
        Summarise where a machine ID's posts were created

        :param dict locations:  Country codes mapped to how often they occurred
        :param int limit:  Name at most this many countries
        :return str:  Something like `US (50%), NL (10%), GB (5%)`
        """
        total = sum(locations.values())
        if not total:
            return "no locations recorded"

        described = []
        for code, count in sorted(locations.items(), key=lambda item: (-item[1], item[0]))[:limit]:
            share = count / total
            described.append(f"{code} ({'<1%' if share < 0.005 else format(share, '.0%')})")

        return andify(described)

    @staticmethod
    def machine_locations(machine, limit=MACHINE_LOCATION_LIMIT):
        """
        The countries a machine ID is taken to belong to

        This is the same set of countries the query form names for the machine,
        so that what someone selects is what they saw.

        :param dict machine:  Machine data, with a `locations` dictionary
        :param int limit:  Consider at most this many countries
        :return list:  Country codes, most common first
        """
        locations = machine.get("locations", {})
        return [code for code, _ in sorted(locations.items(), key=lambda item: (-item[1], item[0]))[:limit]]

    @staticmethod
    def count_machines(tails):
        """
        Count how many of the known posts each machine ID minted

        Counted from the patterns rather than from the seeded machine data, so
        that this also works with a list of patterns configured by an
        administrator.

        :param dict tails:  Patterns mapped to how often they occurred
        :return dict:  Machine IDs, as integers, mapped to a post count
        """
        machines = {}
        for tail, count in tails.items():
            machine = int(tail[TAIL_MACHINE_SLICE[0]:TAIL_MACHINE_SLICE[1]], 2)
            machines[machine] = machines.get(machine, 0) + count

        return machines

    @classmethod
    def rank_machines(cls, tails):
        """
        Order machine IDs by how many of the known posts they minted

        :param dict tails:  Patterns mapped to how often they occurred
        :return list:  Machine IDs, as integers, most common first
        """
        counted = cls.count_machines(tails)
        return [machine for machine, _ in sorted(counted.items(), key=lambda item: (-item[1], item[0]))]

    @staticmethod
    def parse_machine_ids(value):
        """
        Read a list of machine IDs from user input

        A machine ID is six bits, so it may be written either as six binary
        digits or as the number those digits represent. Six binary digits are
        always read as bits: the only values that could be read both ways are
        `000000` and `000001`, which mean the same thing either way.

        :param str value:  Newline- or comma-separated machine IDs
        :return tuple:  A set of machine IDs as integers, and a list of the
          entries that could not be read
        """
        machines = set()
        rejected = []

        for token in re.split(r"[\s,;]+", str(value)):
            token = token.strip()
            if not token:
                continue

            if re.fullmatch(r"[01]{%i}" % MACHINE_ID_LENGTH, token):
                machines.add(int(token, 2))
            elif token.isdigit() and int(token) < 2 ** MACHINE_ID_LENGTH:
                machines.add(int(token))
            else:
                rejected.append(token)

        return machines, rejected

    @staticmethod
    def parse_tail_setting(value):
        """
        Read ID patterns from the data source setting

        Accepts a pattern per line, in any of the forms people are likely to
        have them in: 22 bits, the number those bits represent, 64 bits, or a
        full post ID. An optional second value on the line is how often the
        pattern was observed, which is what patterns get ranked by.

        Patterns that do not belong to a video post are dropped. TikTok mints
        user, comment and music IDs with the same scheme and a different value
        in the entity type bits, so a list built from the wrong column - or with
        a different bit offset - consists entirely of such patterns, and every
        ID generated from it is guaranteed not to exist. Left unchecked that
        costs a whole query's worth of requests to discover.

        :param str value:  Setting value
        :return tuple:  Patterns of 22 bits mapped to how often they occurred,
          and how many entries were dropped, per reason
        """
        tails = {}
        rejected = {}

        def reject(reason):
            rejected[reason] = rejected.get(reason, 0) + 1

        for line in re.split(r"[\r\n]+", str(value)):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            parts = [part for part in re.split(r"[,;\t ]+", line) if part]
            pattern = parts[0]
            count = max(1, convert_to_int(parts[1], 1)) if len(parts) > 1 else 1

            if re.fullmatch(r"[01]{%i}" % TAIL_LENGTH, pattern):
                tail = pattern
            elif re.fullmatch(r"[01]{%i}" % ID_LENGTH, pattern):
                tail = pattern[TAIL_SLICE[0]:TAIL_SLICE[1]]
            elif set(pattern) <= {"0", "1"}:
                # nothing but zeroes and ones, yet not 22 or 64 of them: a bit
                # string that lost its leading zeros, which is what printing
                # int(bits) rather than the bits themselves produces. Reading it
                # as a decimal number gives a different pattern that looks
                # perfectly valid and matches nothing
                reject("look like bit patterns that lost their leading zeros")
                continue
            elif pattern.startswith("0"):
                # a leading zero means this was meant as binary, but it is not
                # as long as either of the two binary forms - reading it as a
                # number instead would quietly give the wrong pattern
                reject("could not be read as an ID pattern")
                continue
            elif pattern.isdigit() and 0 < int(pattern) < 2 ** ID_LENGTH:
                number = int(pattern)
                tail = f"{number:0{TAIL_LENGTH}b}" if number < 2 ** TAIL_LENGTH \
                    else f"{number:064b}"[TAIL_SLICE[0]:TAIL_SLICE[1]]
            else:
                reject("could not be read as an ID pattern")
                continue

            if int(tail[TAIL_TYPE_SLICE[0]:TAIL_TYPE_SLICE[1]], 2) != VIDEO_ENTITY_TYPE:
                reject("are not video post patterns")
                continue

            tails[tail] = tails.get(tail, 0) + count

        return tails, rejected

    @classmethod
    def select_tails(cls, tails, machine_ids=0, machines=None, coverage=100):
        """
        Narrow down and order the ID patterns to sample with

        Patterns are ordered by how often they were observed, so that dropping
        some of them drops the rarest first.

        The coverage limit is applied after the machine ID limits, so that
        asking for 99% coverage of a handful of machine IDs means 99% of what
        *those* machines posted, rather than a number that silently means
        something else once the machines are narrowed down.

        :param dict tails:  Patterns mapped to how often they occurred
        :param int machine_ids:  Keep only patterns belonging to this many of
          the most common machine IDs; 0 for all
        :param set|None machines:  Keep only patterns belonging to these machine
          IDs; `None` for all
        :param float coverage:  Keep the most common patterns accounting for at
          least this percentage of the known posts; 100 for all
        :return list:  Patterns of 22 bits, most common first
        """
        if not tails:
            return []

        if machine_ids > 0:
            keep = set(cls.rank_machines(tails)[:machine_ids])
            machines = keep if machines is None else (machines & keep)

        if machines is not None:
            tails = {tail: count for tail, count in tails.items()
                     if int(tail[TAIL_MACHINE_SLICE[0]:TAIL_MACHINE_SLICE[1]], 2) in machines}

        ordered = [tail for tail, _ in sorted(tails.items(), key=lambda item: (-item[1], item[0]))]
        if coverage >= 100:
            return ordered

        # take patterns from the most common down until the ones taken account
        # for the requested share of the posts we know about
        total = sum(tails.values())
        wanted = total * coverage / 100
        taken = 0
        for position, tail in enumerate(ordered):
            taken += tails[tail]
            if taken >= wanted:
                return ordered[:position + 1]

        return ordered

    @classmethod
    def get_pattern_options(cls, tails):
        """
        Build the 'limit by most common ID patterns' dropdown

        Every candidate ID costs a request, and the rarest patterns cost the
        same as the common ones while almost never yielding a post - so leaving
        them out buys a better hit rate. What it costs is coverage, which is the
        whole point of the method, so each option says what it gives up and what
        it buys rather than only how many patterns are left.

        Targets that come out at the same number of patterns are folded into
        one, which is what keeps a thinly seeded instance from offering eight
        options that all do the same thing.

        :param dict tails:  Patterns mapped to how often they occurred
        :return dict:  Option values (a coverage target) mapped to a label
        """
        if not tails:
            return {}

        total = sum(tails.values())
        options = {}
        sizes = set()

        for target in PATTERN_COVERAGE_TARGETS:
            kept = cls.select_tails(tails, coverage=target)
            if not kept or len(kept) in sizes:
                continue

            sizes.add(len(kept))
            share = sum(tails[tail] for tail in kept) / total
            rate = share / (len(kept) / len(tails))

            options[f"{target:g}"] = f"all {len(tails):,}/{len(tails):,} (100%)" if len(kept) == len(tails) \
                else f"{len(kept):,}/{len(tails):,} ({share:.1%} of posts, ~{rate:.1f}x hit rate)"

            if len(options) >= MAX_PATTERN_OPTIONS:
                break

        return options

    @classmethod
    def resolve_machines(cls, query, tails, machine_data):
        """
        Work out which machine IDs a query wants to sample with

        :param dict query:  Query parameters
        :param dict tails:  Patterns mapped to how often they occurred
        :param dict machine_data:  Machine IDs mapped to their post and location
          counts, as returned by `get_machines()`
        :return tuple:  A set of machine IDs, or `None` to use all of them, and
          a description of what could not be resolved (empty if all is well)
        """
        mode = query.get("machine_id_mode", "all")

        if mode == "location":
            wanted = query.get("machine_id_locations", [])
            if type(wanted) is str:
                wanted = [code for code in re.split(r"[\s,;]+", wanted) if code]

            if not wanted:
                return None, "No locations were selected."

            wanted = set(wanted)
            machines = {machine for machine, data in machine_data.items()
                        if wanted & set(cls.machine_locations(data))}

            if not machines:
                return set(), (f"No machine IDs are associated with {', '.join(sorted(wanted))}. The locations known "
                               f"to this 4CAT instance may have changed since this query was made.")

            return machines, ""

        elif mode == "common":
            amount = max(0, convert_to_int(query.get("machine_id_count"), 0))
            return (set(cls.rank_machines(tails)[:amount]) if amount else None), ""

        elif mode == "custom":
            machines, rejected = cls.parse_machine_ids(query.get("machine_id_custom", ""))
            if not machines:
                return set(), "No machine IDs could be read from the custom list."

            return machines, (f"Ignored {len(rejected)} entry/entries in the custom machine ID list that could not be "
                              f"read: {', '.join(rejected[:10])}." if rejected else "")

        return None, ""

    @staticmethod
    def map_item(item):
        """
        Posts are collected from the same pages as the other TikTok data sources

        :param item:
        :return:
        """
        return SearchTikTok.map_item(item)
