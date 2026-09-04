"""
Keep the TikTok ID patterns this 4CAT instance samples with up to date

The ID sampling data source can only generate candidate post IDs if it knows
which of the four million possible ID patterns TikTok actually mints. Those
patterns are read from the TikTok datasets on this server, which means reading
hundreds of thousands of post IDs. That is too slow to do while someone waits
for a query, and the answer changes as datasets are added and as TikTok retires
and commissions machines, so it happens here instead: once when this 4CAT
instance first starts, and daily after that.

Private datasets are read too. A dataset is private by default in 4CAT rather
than by a decision of its owner, and what is derived here is a property of
TikTok's ID scheme rather than of the datasets: post IDs go in, and bit patterns
with no timestamp, no author and no dataset of origin come out.

Alongside the patterns this records, per machine ID, which countries the posts
minted by that machine were created in. That is what lets someone sample a
region rather than the platform as a whole - loosely, since a machine ID
correlates with a location but does not determine it (Steel et al. 2026).
"""
import json
import time
import csv
import re

from backend.lib.worker import BasicWorker
from common.lib.exceptions import WorkerInterruptedException
from common.lib.helpers import convert_to_int
from datasources.tiktok_sample.search_tiktok_sample import (ID_LENGTH, TAIL_SLICE, TAIL_TYPE_SLICE,
                                                            TAIL_MACHINE_SLICE, VIDEO_ENTITY_TYPE, SEEDED_TYPES,
                                                            TAIL_CACHE_FILE, SEED_INTERVAL, CACHE_VERSION,
                                                            NO_PATTERNS_ANYWHERE)


class SeedTikTokSample(BasicWorker):
    """
    Derive TikTok ID patterns from the TikTok datasets on this server
    """
    type = "tiktok-sample-seed"
    max_workers = 1

    @classmethod
    def ensure_job(cls, config=None):
        """
        Make sure this runs on startup and then daily

        The job is stored in the database, so the first startup of a 4CAT
        instance runs it right away - i.e. when there is no cache file yet -
        and later startups leave the existing schedule alone.

        :param config:  Configuration reader
        :return dict:  Job parameters
        """
        return {"remote_id": "localhost", "interval": SEED_INTERVAL}

    def work(self):
        """
        Scan the datasets on this server and cache what was found
        """
        tails, machines, posts_scanned, datasets_scanned, problem = self.seed()

        if not tails:
            # nothing to cache; leave any existing cache in place, since stale
            # patterns are more useful than none at all
            self.log.info(f"No TikTok ID patterns could be seeded: {problem}")
            return

        self.log.info(f"Seeded {len(tails):,} TikTok ID pattern(s) across {len(machines)} machine ID(s) from "
                      f"{posts_scanned:,} post ID(s) in {datasets_scanned:,} dataset(s).")
        self.save_cache(tails, machines, posts_scanned, datasets_scanned)

    def seed(self):
        """
        Collect ID patterns from the TikTok datasets on this server

        Reads post IDs from finished TikTok datasets, most recent first, until
        enough of them have been seen. Only IDs of video posts count - other
        entities (users, comments, livestreams) use the same ID scheme but
        different patterns, and including those would inflate the search space
        for nothing.

        Every dataset is read, private ones included. What comes out of this is
        which of the four million possible ID patterns TikTok creates, which is a
        property of TikTok's infrastructure rather than of anyone's data: the
        timestamp bits are discarded and nothing that identifies a post, an
        author or a dataset is kept. The one exception is the country counts
        per machine ID, which are aggregated over every dataset read - see
        `records_per_dataset()` for why no single dataset can dominate them.

        :return tuple:  Patterns of 22 bits mapped to how often they occurred,
          machine IDs mapped to their post and location counts, the number of
          unique post IDs and datasets read, and an explanation of why there are
          no patterns (empty if there are some)
        """
        limit = convert_to_int(self.config.get("tiktok-sample-search.seed-limit", 250_000), 250_000)
        data_path = self.config.get("PATH_DATA")

        datasets = self.db.fetchall(
            "SELECT key, type, result_file FROM datasets WHERE type IN %s AND is_finished = TRUE "
            "AND key_parent = '' ORDER BY timestamp DESC", (SEEDED_TYPES,))

        if not datasets:
            return {}, {}, 0, 0, NO_PATTERNS_ANYWHERE

        seen = set()
        tails = {}
        machines = {}
        scanned = set()

        # first pass: no dataset may supply more than its share. second pass:
        # if that left the cache short - because most datasets on this server
        # are small - take the rest wherever it can be found, since a cache
        # that covers a fifth of the patterns is worse than one drawn unevenly
        for cap in (self.records_per_dataset(limit, len(datasets)), limit):
            if len(seen) >= limit:
                break

            scanned |= self.scan(datasets, data_path, cap, limit, seen, tails, machines)

        if tails:
            return tails, machines, len(seen), len(scanned), ""

        # there were datasets to read, but nothing usable came out of them - say
        # which of the two ways that happened, since the fix differs
        if not scanned:
            return {}, {}, 0, 0, (f"Found {len(datasets):,} TikTok dataset(s), but none of their result files could "
                                  f"be read.")

        return {}, {}, len(seen), len(scanned), (f"Read {len(seen):,} post ID(s) from {len(scanned):,} TikTok "
                                                 f"dataset(s), but none of them were video post IDs, so there are no "
                                                 f"patterns to sample with.")

    def scan(self, datasets, data_path, cap, limit, seen, tails, machines):
        """
        Read post IDs from a list of datasets, newest first

        `seen`, `tails` and `machines` are updated in place, so that a second
        pass with a different cap picks up where the first left off.

        :param list datasets:  Dataset records, newest first
        :param Path data_path:  Where result files live
        :param int cap:  Read at most this many new post IDs per dataset
        :param int limit:  Stop once this many post IDs have been read in total
        :param set seen:  Post IDs read so far
        :param dict tails:  Pattern tally
        :param dict machines:  Machine ID tally
        :return set:  Keys of the datasets whose result files could be read
        """
        scanned = set()

        for record in datasets:
            if self.interrupted:
                raise WorkerInterruptedException("Interrupted while seeding TikTok ID patterns")

            if len(seen) >= limit:
                break

            if not record["result_file"]:
                continue

            path = data_path.joinpath(record["result_file"])
            if not path.exists():
                continue

            scanned.add(record["key"])
            from_this_dataset = 0

            for index, (post_id, location) in enumerate(self.iterate_posts(path)):
                if index % 10_000 == 0 and self.interrupted:
                    raise WorkerInterruptedException("Interrupted while seeding TikTok ID patterns")

                if post_id not in seen:
                    seen.add(post_id)
                    from_this_dataset += 1
                    self.record_post(post_id, location, tails, machines)

                if len(seen) >= limit or from_this_dataset >= cap:
                    break

        return scanned

    @staticmethod
    def records_per_dataset(limit, datasets, spread=10):
        """
        How many post IDs to read from any one dataset

        Reading datasets to exhaustion, newest first, means the newest large
        dataset can supply the entire cache on its own.

        So no dataset may supply more than its share, unless there are too few
        datasets for that to be possible - with fewer than `spread` of them a
        single one may still fill the cache, since half a cache would be worse.

        :param int limit:  Post IDs wanted in total
        :param int datasets:  Datasets available to read
        :param int spread:  Read from at least this many datasets, if there are
          that many
        :return int:  Post IDs to read per dataset
        """
        return max(1, limit // max(1, min(datasets, spread)))

    @staticmethod
    def record_post(post_id, location, tails, machines):
        """
        Add one post ID to the tallies, if it is a video post ID

        :param int post_id:  Post ID
        :param str location:  Country the post was created in; may be empty
        :param dict tails:  Pattern tally, updated in place
        :param dict machines:  Machine ID tally, updated in place
        """
        tail = f"{post_id:0{ID_LENGTH}b}"[TAIL_SLICE[0]:TAIL_SLICE[1]]
        if int(tail[TAIL_TYPE_SLICE[0]:TAIL_TYPE_SLICE[1]], 2) != VIDEO_ENTITY_TYPE:
            return

        tails[tail] = tails.get(tail, 0) + 1

        machine = str(int(tail[TAIL_MACHINE_SLICE[0]:TAIL_MACHINE_SLICE[1]], 2))
        if machine not in machines:
            machines[machine] = {"posts": 0, "located": 0, "locations": {}}

        machines[machine]["posts"] += 1

        # `located` is counted separately from the location tallies because the
        # query form drops the rarest countries from those, and how many posts
        # said anything at all is exactly what it needs to be honest about
        if location:
            machines[machine]["located"] += 1
            machines[machine]["locations"][location] = machines[machine]["locations"].get(location, 0) + 1

    @staticmethod
    def normalise_location(value):
        """
        Read a country from a post's `location_created`

        TikTok reports this as a two-letter country code. Anything else is
        discarded rather than guessed at, since these end up as the labels
        someone picks a sample from.

        :param value:  Value from the dataset
        :return str:  A two-letter country code, or an empty string
        """
        value = str(value).strip().upper() if value else ""
        return value if re.fullmatch(r"[A-Z]{2}", value) else ""

    @classmethod
    def iterate_posts(cls, path):
        """
        Read TikTok post IDs and locations from a dataset result file

        NDJSON files hold the objects TikTok itself returned, CSV files hold
        the mapped version of those, so the location lives under a different
        key in each.

        :param Path path:  Path to an .ndjson or .csv dataset result file
        :return:  Yields tuples of a post ID (as an integer) and a country code
          (which may be an empty string)
        """
        try:
            if path.suffix == ".ndjson":
                with path.open(encoding="utf-8") as infile:
                    for line in infile:
                        try:
                            post = json.loads(line)
                            post_id = int(post.get("id"))
                        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
                            continue

                        if 0 < post_id < 2 ** ID_LENGTH:
                            yield post_id, cls.normalise_location(post.get("locationCreated"))

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
                            yield post_id, cls.normalise_location(row.get("location_created"))

        except (OSError, csv.Error, UnicodeDecodeError):
            return

    def save_cache(self, tails, machines, posts_scanned, datasets_scanned):
        """
        Cache the seeded ID patterns for the data source to read

        :param dict tails:  Patterns mapped to how often they occurred
        :param dict machines:  Machine IDs mapped to their post and location counts
        :param int posts_scanned:  Unique post IDs the patterns were found in
        :param int datasets_scanned:  Datasets those posts came from
        """
        try:
            path = self.config.get("PATH_CONFIG").joinpath(TAIL_CACHE_FILE)
            with path.open("w", encoding="utf-8") as outfile:
                json.dump({
                    "version": CACHE_VERSION,
                    "created": int(time.time()),
                    "posts_scanned": posts_scanned,
                    "datasets_scanned": datasets_scanned,
                    "tails": tails,
                    "machines": machines
                }, outfile)
        except (OSError, TypeError) as e:
            self.log.error(f"Could not cache seeded TikTok ID patterns: {e}")
