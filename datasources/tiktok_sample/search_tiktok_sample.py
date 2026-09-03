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
import csv
import re

import psycopg2

from datetime import datetime, timezone

from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_datetime

from backend.lib.search import Search
from backend.lib.proxied_requests import FailedProxiedRequest
from common.lib.helpers import UserInput, convert_to_int, timify
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
VIDEO_ENTITY_TYPE = 13  # 0xd - the entity type of a video post

# any username resolves, as long as the ID after it exists
DUMMY_USERNAME = "fourcat"

# data source types whose result files contain TikTok post IDs we can seed
SEEDED_TYPES = ("tiktok-search", "tiktok-urls-search", "tiktok-sample-search")

# where the seeded tails are cached between queries
TAIL_CACHE_FILE = "tiktok-sample-tails.json"

# longest time range that may be sampled, in seconds
MAX_DURATION = 10

# what to tell someone who has no ID patterns and no way to come by them. The
# data source simply cannot run in that state, so it says so rather than
# generating IDs that are certain not to exist
ASK_FOR_PATTERNS = ("Ask an administrator to fill in the 'Known TikTok ID patterns' setting for this data source, or "
                    "make a TikTok dataset on this server public so that patterns can be read from it.")
NO_PATTERNS_ANYWHERE = ("This 4CAT instance has no TikTok ID patterns to sample with: none are configured, and there "
                        "are no public TikTok datasets on this server to derive them from. " + ASK_FOR_PATTERNS)

# how many candidate IDs may come back empty before we say something is wrong.
# at the ~1/125 rate Steel et al. report, seeing nothing in this many requests
# has a probability of well under a percent
ZERO_HIT_WARNING_AFTER = 2000

# how many tails Steel et al. ended up with; used only to estimate the size of a
# query when this 4CAT instance has not seeded any tails yet
REFERENCE_TAIL_COUNT = 504


class SearchTikTokSample(Search):
    """
    Sample TikTok posts by generating candidate post IDs
    """
    type = "tiktok-sample-search"  # job ID
    category = "Search"  # category
    title = "Sample TikTok posts by ID"  # title displayed in UI
    description = ("Collect a near-complete sample of the TikTok posts made during a short time range, by generating "
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
                       "last 22 bits are used). If this is left empty, 4CAT seeds patterns from the public TikTok "
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
            patterns_info = ("**No ID patterns are known to this 4CAT instance yet.** When you start this query, 4CAT "
                             "first reads the post IDs of the public TikTok datasets on this server to find them. If "
                             "there are no public TikTok datasets here, the query cannot run, and an administrator "
                             "will need to paste a list of patterns into the `tiktok-sample-search.id-patterns` setting. "
                             "Note that TikTok's infrastructure changes over time, so a list that worked a year ago "
                             "may no longer cover the machines minting IDs today.")

        return {
            "intro": {
                "type": UserInput.OPTION_INFO,
                "help": "This data source collects a near-complete sample of everything posted to TikTok during a "
                        "short time range, using the method of [Steel et al. "
                        "(2026)](https://journalqd.org/article/view/9514). It does not search: it works out every ID "
                        "TikTok could have minted during the range you give and requests each one.\n\nThis is slow "
                        "and expensive. Fewer than one in a hundred candidate IDs corresponds to a post that ever "
                        "existed, and fewer still to one that can still be retrieved, so expect a few thousand posts "
                        "per million requests. Steel et al. needed five months to collect 83 minutes of TikTok."
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
                "tooltip": "For example 2024-04-10 17:00:00. Always read as UTC. This is the time encoded in the post "
                           "ID, which for scheduled posts is when the post was created rather than when it went live."
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
                "help": "Milliseconds per second",
                "tooltip": "Only sample the first this many milliseconds of each second. Steel et al. found the "
                           "millisecond field to be uniformly distributed, so lowering this yields an unbiased random "
                           "subsample of the posts in the range: at 100, you collect roughly a tenth of them for a "
                           "tenth of the requests."
            },
            "sampling-divider": {
                "type": UserInput.OPTION_DIVIDER
            },
            "sampling-info": {
                "type": UserInput.OPTION_INFO,
                "help": "The two settings below also reduce the number of requests, but unlike the millisecond "
                        "setting they do so by leaving parts of TikTok out rather than by sampling it more thinly. "
                        "Use them only if you understand what they exclude."
            },
            "max_patterns": {
                "type": UserInput.OPTION_TEXT,
                "coerce_type": int,
                "default": 0,
                "min": 0,
                "help": "Most common ID patterns",
                "tooltip": "Only use this many of the most frequently observed ID patterns; 0 uses all of them. Rarer "
                           "patterns are the ones that give the method its high coverage, so dropping them lowers the "
                           "share of posts you find, in ways that are hard to predict."
            },
            "machine_ids": {
                "type": UserInput.OPTION_TEXT,
                "coerce_type": int,
                "default": 0,
                "min": 0,
                "help": "Most common machine IDs",
                "tooltip": "Only use patterns belonging to this many of the most frequently observed machine IDs; 0 "
                           "uses all of them. Steel et al. found that these bits identify the datacentre that minted "
                           "the ID and that they correlate with where a post comes from, but they stress that how "
                           "well this works as a way of sampling a region is not yet established. Expect this to skew "
                           "which parts of the world end up in your dataset."
            }
        }

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
            raise QueryParametersException(f"'{start_time}' could not be read as a date and time. Use a format like "
                                           f"2024-04-10 17:00:00.")

        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)

        start = int(start.timestamp())
        duration = max(1, min(MAX_DURATION, convert_to_int(query.get("duration"), 1)))
        milliseconds = max(1, min(1000, convert_to_int(query.get("milliseconds"), 1000)))
        max_patterns = max(0, convert_to_int(query.get("max_patterns"), 0))
        machine_ids = max(0, convert_to_int(query.get("machine_ids"), 0))

        now = int(datetime.now(tz=timezone.utc).timestamp())
        if start < 0:
            raise QueryParametersException("The start of the range must be after 1 January 1970.")
        elif start + duration > now:
            raise QueryParametersException("The range to sample must lie fully in the past.")

        # figure out how many candidate IDs this would generate. if this 4CAT
        # instance has not seeded any ID patterns yet we cannot know, so fall
        # back to the number Steel et al. arrived at - the worker checks again
        # once it knows the real number
        known_tails, _, tail_problem = SearchTikTokSample.get_known_tails(config)
        if not known_tails and tail_problem:
            raise QueryParametersException(tail_problem)
        elif not known_tails and SearchTikTokSample.count_seedable_datasets(config) == 0:
            # nothing configured, nothing cached and nothing to seed from, so
            # this query could only ever request IDs that cannot exist
            raise QueryParametersException(NO_PATTERNS_ANYWHERE)

        if known_tails:
            tail_count = len(SearchTikTokSample.select_tails(known_tails, max_patterns, machine_ids))
            if not tail_count:
                raise QueryParametersException("The chosen limits on ID patterns and machine IDs leave no patterns to "
                                               "sample with.")
        else:
            tail_count = REFERENCE_TAIL_COUNT if not max_patterns else min(max_patterns, REFERENCE_TAIL_COUNT)

        candidates = duration * milliseconds * tail_count
        max_candidates = convert_to_int(config.get("tiktok-sample-search.max-candidates", 1000000), 1000000)

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
            "max_patterns": max_patterns,
            "machine_ids": machine_ids
        }

    def get_items(self, query):
        """
        Generate candidate TikTok post IDs and request them all

        :param dict query:  Search query parameters
        """
        tails, source, tail_problem = self.get_known_tails(self.config)
        if not tails and tail_problem:
            self.dataset.finish_with_error(tail_problem)
            return
        elif not tails:
            tails, seed_problem = self.seed_tails()
            source = "seeded from public TikTok datasets on this server"

            if not tails:
                self.dataset.finish_with_error(seed_problem or NO_PATTERNS_ANYWHERE)
                return

        self.dataset.log(f"Using {len(tails):,} ID patterns ({source}).")
        if tail_problem:
            self.dataset.log(tail_problem)

        selected = self.select_tails(tails, query["max_patterns"], query["machine_ids"])
        if not selected:
            self.dataset.finish_with_error("The chosen limits on ID patterns and machine IDs leave no patterns to "
                                           "sample with.")
            return

        # the number of patterns may have changed since the query was validated
        # (e.g. because they had not been seeded yet), so check the budget
        # again and drop the rarest patterns if it no longer fits
        max_candidates = convert_to_int(self.config.get("tiktok-sample-search.max-candidates", 1_000_000), 1_000_000)
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
        machines = sorted({int(tail[TAIL_MACHINE_SLICE[0]:TAIL_MACHINE_SLICE[1]], 2) for tail in selected})
        start_readable = datetime.fromtimestamp(query["start_time"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

        # record exactly what was sampled, so the dataset can be reproduced
        self.dataset.log(f"Sampling {query['duration']} second(s) from {start_readable} UTC "
                         f"(timestamps {query['start_time']} to {query['start_time'] + query['duration'] - 1}).")
        self.dataset.log(f"Sampling milliseconds 0 to {query['milliseconds'] - 1} of each second.")
        self.dataset.log(f"Using {len(selected):,} ID pattern(s) covering {len(machines)} machine ID(s): "
                         f"{', '.join(str(machine) for machine in machines)}.")
        self.dataset.log("ID patterns used (bits 42-63 of the post ID):\n" + "\n".join(selected))

        self.dataset.update_status(f"Requesting {candidates:,} candidate TikTok post IDs")

        scraper = TikTokScraper(processor=self, config=self.config)
        urls = self.candidate_urls(query["start_time"], query["duration"], query["milliseconds"], selected)

        requested = 0
        collected = 0
        outcomes = {}
        interrupted = False
        warned = False

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

            if requested % 500 == 0:
                self.dataset.update_status(f"Requested {requested:,} of {candidates:,} candidate IDs, found "
                                           f"{collected:,} post(s)"
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

    def seed_tails(self):
        """
        Collect ID patterns from the public TikTok datasets on this server

        Reads post IDs from public, finished TikTok datasets, most recent first,
        until enough of them have been seen. Only IDs of video posts count -
        other entities (users, comments, livestreams) use the same ID scheme but
        different patterns, and including those would inflate the search space
        for nothing.

        The result is cached so the query form can tell users how large a range
        they can sample before they submit anything.

        :return tuple:  Patterns of 22 bits mapped to how often they occurred,
          and an explanation of why there are none (empty if there are some)
        """
        limit = convert_to_int(self.config.get("tiktok-sample-search.seed-limit", 250000), 250000)
        data_path = self.config.get("PATH_DATA")

        datasets = self.db.fetchall(
            "SELECT key, type, result_file FROM datasets WHERE type IN %s AND is_finished = TRUE "
            "AND is_private = FALSE AND key_parent = '' ORDER BY timestamp DESC", (SEEDED_TYPES,))

        if not datasets:
            return {}, NO_PATTERNS_ANYWHERE

        self.dataset.update_status(f"Looking for TikTok ID patterns in {len(datasets):,} public dataset(s) on this "
                                   f"server")

        seen = set()
        tails = {}
        scanned = 0

        for record in datasets:
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while seeding TikTok ID patterns")

            if len(seen) >= limit:
                break

            if not record["result_file"]:
                continue

            path = data_path.joinpath(record["result_file"])
            if not path.exists():
                continue

            scanned += 1
            for index, post_id in enumerate(self.iterate_post_ids(path)):
                if index % 10000 == 0 and self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while seeding TikTok ID patterns")

                if post_id in seen:
                    continue

                seen.add(post_id)
                tail = f"{post_id:0{ID_LENGTH}b}"[TAIL_SLICE[0]:TAIL_SLICE[1]]
                if int(tail[TAIL_TYPE_SLICE[0]:TAIL_TYPE_SLICE[1]], 2) == VIDEO_ENTITY_TYPE:
                    tails[tail] = tails.get(tail, 0) + 1

                if len(seen) >= limit:
                    break

            self.dataset.update_status(f"Found {len(tails):,} ID pattern(s) in {len(seen):,} post ID(s) from "
                                       f"{scanned:,} dataset(s)")

        self.dataset.log(f"Harvested {len(tails):,} ID pattern(s) from {len(seen):,} unique post ID(s) across "
                         f"{scanned:,} public dataset(s).")

        if tails:
            self.save_tail_cache(tails, len(seen), scanned)
            return tails, ""

        # there were datasets to read, but nothing usable came out of them - say
        # which of the two ways that happened, since the fix differs
        if not scanned:
            return {}, (f"Found {len(datasets):,} public TikTok dataset(s), but none of their result files could be "
                        f"read; they have most likely been deleted from disk. {ASK_FOR_PATTERNS}")

        return {}, (f"Read {len(seen):,} post ID(s) from {scanned:,} public TikTok dataset(s), but none of them were "
                    f"video post IDs, so there are no patterns to sample with. {ASK_FOR_PATTERNS}")

    @staticmethod
    def iterate_post_ids(path):
        """
        Read TikTok post IDs from a dataset result file

        :param Path path:  Path to an .ndjson or .csv dataset result file
        :return:  Yields post IDs, as integers
        """
        try:
            if path.suffix == ".ndjson":
                with path.open(encoding="utf-8") as infile:
                    for line in infile:
                        try:
                            post_id = int(json.loads(line).get("id"))
                        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
                            continue

                        if 0 < post_id < 2 ** ID_LENGTH:
                            yield post_id

            elif path.suffix == ".csv":
                with path.open(encoding="utf-8") as infile:
                    reader = csv.DictReader(infile)
                    if "id" not in (reader.fieldnames or []):
                        return

                    for row in reader:
                        try:
                            post_id = int(row["id"])
                        except (TypeError, ValueError):
                            continue

                        if 0 < post_id < 2 ** ID_LENGTH:
                            yield post_id

        except (OSError, csv.Error, UnicodeDecodeError):
            return

    def save_tail_cache(self, tails, posts_scanned, datasets_scanned):
        """
        Cache seeded ID patterns so the query form can use them

        :param dict tails:  Patterns mapped to how often they occurred
        :param int posts_scanned:  Unique post IDs the patterns were found in
        :param int datasets_scanned:  Datasets those posts came from
        """
        try:
            path = self.config.get("PATH_CONFIG").joinpath(TAIL_CACHE_FILE)
            with path.open("w", encoding="utf-8") as outfile:
                json.dump({
                    "created": int(time.time()),
                    "posts_scanned": posts_scanned,
                    "datasets_scanned": datasets_scanned,
                    "tails": tails
                }, outfile)
        except (OSError, TypeError) as e:
            self.dataset.log(f"Could not cache seeded TikTok ID patterns: {e}")

    @staticmethod
    def count_seedable_datasets(config):
        """
        Count the public TikTok datasets ID patterns could be seeded from

        Used to tell someone that a query cannot work *before* they wait for it
        to be picked up, rather than after.

        :param config:  Configuration reader
        :return int|None:  How many datasets there are, or `None` if that could
          not be established from here
        """
        try:
            counted = config.db.fetchone(
                "SELECT COUNT(*) AS num FROM datasets WHERE type IN %s AND is_finished = TRUE "
                "AND is_private = FALSE AND key_parent = ''", (SEEDED_TYPES,))
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
                f"digits with the leading zeros intact. Printing int(bits) rather than the bit string itself, or "
                f"taking the IDs from a user, comment or music column instead of the post column, both produce lists "
                f"that parse but can never match a real video.")

        try:
            path = config.get("PATH_CONFIG").joinpath(TAIL_CACHE_FILE)
            if not path.exists():
                return {}, "", ""

            with path.open(encoding="utf-8") as infile:
                cache = json.load(infile)

            tails = {tail: count for tail, count in cache.get("tails", {}).items() if len(tail) == TAIL_LENGTH}
            if not tails:
                return {}, "", ""

            seeded = datetime.fromtimestamp(cache.get("created", 0), tz=timezone.utc).strftime("%d %B %Y")
            return tails, (f"seeded from {cache.get('posts_scanned', 0):,} post IDs in "
                           f"{cache.get('datasets_scanned', 0):,} public dataset(s) on this server on {seeded}"), ""

        except (OSError, AttributeError, ValueError, json.JSONDecodeError):
            return {}, "", ""

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

    @staticmethod
    def select_tails(tails, max_patterns=0, machine_ids=0):
        """
        Narrow down and order the ID patterns to sample with

        Patterns are ordered by how often they were observed, so that dropping
        some of them drops the rarest first.

        :param dict tails:  Patterns mapped to how often they occurred
        :param int max_patterns:  Keep at most this many patterns; 0 for all
        :param int machine_ids:  Keep only patterns belonging to this many of
          the most common machine IDs; 0 for all
        :return list:  Patterns of 22 bits, most common first
        """
        if not tails:
            return []

        if machine_ids > 0:
            machines = {}
            for tail, count in tails.items():
                machine = int(tail[TAIL_MACHINE_SLICE[0]:TAIL_MACHINE_SLICE[1]], 2)
                machines[machine] = machines.get(machine, 0) + count

            keep = {machine for machine, _ in sorted(machines.items(), key=lambda item: (-item[1], item[0]))
                    [:machine_ids]}
            tails = {tail: count for tail, count in tails.items()
                     if int(tail[TAIL_MACHINE_SLICE[0]:TAIL_MACHINE_SLICE[1]], 2) in keep}

        ordered = sorted(tails.items(), key=lambda item: (-item[1], item[0]))
        if max_patterns > 0:
            ordered = ordered[:max_patterns]

        return [tail for tail, _ in ordered]

    @staticmethod
    def map_item(item):
        """
        Posts are collected from the same pages as the other TikTok data sources

        :param item:
        :return:
        """
        return SearchTikTok.map_item(item)
