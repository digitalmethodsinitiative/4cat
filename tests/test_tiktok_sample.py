import json

import pytest

from datasources.tiktok_sample.search_tiktok_sample import (SearchTikTokSample, TAIL_LENGTH, VIDEO_ENTITY_TYPE,
                                                            TAIL_MACHINE_SLICE, NO_PATTERNS_ANYWHERE,
                                                            TAIL_CACHE_FILE)
from datasources.tiktok_sample.seed_tiktok_sample import SeedTikTokSample


"""
The bit arithmetic behind the TikTok ID sampler.

Everything this data source does rests on one claim: that a TikTok post ID is a
64-bit number whose first 32 bits are a UNIX timestamp, whose next 10 bits are
the millisecond within that second, and whose last 22 bits are a pattern drawn
from a small set. If any of those offsets is off by one, the data source will
happily request a million URLs and find nothing, with no error to explain why -
which is exactly the kind of failure that only a test catches.

The anchor is the worked example from Steel et al. (2026), Figure 12: post ID
7341456348594310401 was created at 19:00:07 UTC on 1 March 2024, in millisecond
0, by machine 1. If we can take that ID apart and put it back together, the
offsets are right.
"""

# the example ID from the paper, and what it decomposes into
PAPER_ID = 7341456348594310401
PAPER_TIMESTAMP = 1709316007
PAPER_MILLISECOND = 0
PAPER_MACHINE = 1
PAPER_TAIL = "0000000000110100000001"

# a second, unrelated real video ID, minted in a different millisecond by a
# different machine - so that a test cannot pass on zeroes alone
OTHER_ID = 7079929224945093934
OTHER_TIMESTAMP = 1648424478
OTHER_MILLISECOND = 479
OTHER_MACHINE = 46
OTHER_TAIL = "0000100100110100101110"


def tail_of(post_id):
    return f"{post_id:064b}"[-TAIL_LENGTH:]


# --- the ID layout -----------------------------------------------------------

@pytest.mark.parametrize("post_id,timestamp,millisecond,machine,tail", [
    (PAPER_ID, PAPER_TIMESTAMP, PAPER_MILLISECOND, PAPER_MACHINE, PAPER_TAIL),
    (OTHER_ID, OTHER_TIMESTAMP, OTHER_MILLISECOND, OTHER_MACHINE, OTHER_TAIL),
])
def test_a_generated_id_matches_a_real_one(post_id, timestamp, millisecond, machine, tail):
    """Generating from the parts of a real ID has to give that ID back."""
    urls = list(SearchTikTokSample.candidate_urls(timestamp, 1, millisecond + 1, [tail]))

    assert urls[-1] == f"https://www.tiktok.com/@fourcat/video/{post_id}"
    assert int(tail[TAIL_MACHINE_SLICE[0]:TAIL_MACHINE_SLICE[1]], 2) == machine


def test_real_video_ids_carry_the_video_entity_type():
    """The nibble the harvester filters on has to actually say 'video post'."""
    for post_id in (PAPER_ID, OTHER_ID):
        assert int(f"{post_id:064b}"[52:56], 2) == VIDEO_ENTITY_TYPE


# --- generating candidates ---------------------------------------------------

def test_every_combination_is_generated_exactly_once():
    tails = ["0000000000110100000001", "0000000000110100000010"]
    urls = list(SearchTikTokSample.candidate_urls(PAPER_TIMESTAMP, 3, 4, tails))

    assert len(urls) == 3 * 4 * len(tails)
    assert len(set(urls)) == len(urls)


def test_a_run_cut_short_still_covers_the_whole_range():
    """
    Milliseconds are the outer loop on purpose.

    A sample that is interrupted should be a thinner sample of the whole range,
    not a complete sample of its first second, so every second has to appear
    before any millisecond is repeated.
    """
    urls = list(SearchTikTokSample.candidate_urls(PAPER_TIMESTAMP, 5, 2, [PAPER_TAIL]))
    first_pass = [int(url.split("/")[-1]) >> 32 for url in urls[:5]]

    assert first_pass == list(range(PAPER_TIMESTAMP, PAPER_TIMESTAMP + 5))


# --- reading patterns from the data source setting ---------------------------

def test_all_four_ways_of_writing_a_pattern_agree():
    """
    People will have their pattern lists in whichever form their own script
    produced, so all of these have to land on the same 22 bits.
    """
    setting = "\n".join([
        PAPER_TAIL,  # the 22 bits themselves
        str(int(PAPER_TAIL, 2)),  # the number those bits represent
        f"{PAPER_ID:064b}",  # a full ID in binary
        str(PAPER_ID),  # a full ID as TikTok writes it
    ])

    assert SearchTikTokSample.parse_tail_setting(setting)[0] == {PAPER_TAIL: 4}


def test_occurrence_counts_are_read_and_added_up():
    setting = f"{PAPER_TAIL}, 10\n{OTHER_TAIL} 3\n{PAPER_TAIL},5"

    assert SearchTikTokSample.parse_tail_setting(setting)[0] == {PAPER_TAIL: 15, OTHER_TAIL: 3}


def test_comments_blanks_and_nonsense_are_skipped():
    setting = f"# a comment\n\n{PAPER_TAIL}\nnot a pattern\n0\n"

    assert SearchTikTokSample.parse_tail_setting(setting)[0] == {PAPER_TAIL: 1}


def test_a_half_written_binary_pattern_is_refused_rather_than_guessed():
    """
    '01010' is either binary 10 or the number 1010, and there is no telling
    which. Guessing would hand back a pattern that looks fine and finds nothing,
    so an unpadded binary string is dropped instead.
    """
    assert SearchTikTokSample.parse_tail_setting("01010")[0] == {}
    assert SearchTikTokSample.parse_tail_setting(str(int(PAPER_TAIL, 2)))[0] == {PAPER_TAIL: 1}


def test_a_pattern_that_lost_its_leading_zeros_is_refused():
    """
    The mistake that produced the bad list: printing int(bits) instead of bits.

    That turns '0000000000110100000001' into the decimal number 110100000001,
    which is a plausible enough integer that reading it as an ID yields a
    well-formed pattern - one that has nothing to do with the original.
    """
    stripped = str(int(PAPER_TAIL))  # int() of the *string*, so base 10, zeros gone
    assert stripped == "110100000001"

    tails, rejected = SearchTikTokSample.parse_tail_setting(stripped)

    assert tails == {}
    assert rejected == {"look like bit patterns that lost their leading zeros": 1}


def test_a_pattern_that_is_not_a_video_post_is_rejected():
    """
    The failure this catches cost 25,000 wasted requests once.

    A pattern list built from the wrong column, or sliced at the wrong bit
    offset, parses perfectly well - it is just not a list of video posts, so
    every ID generated from it is guaranteed not to exist. TikTok answers each
    one with 'item doesn't exist', which looks exactly like an honest miss.
    """
    # a real pattern seen in the wild whose entity type bits say 7, not 13
    not_a_video = "0000001011011111110110"
    assert int(not_a_video[10:14], 2) != VIDEO_ENTITY_TYPE

    tails, rejected = SearchTikTokSample.parse_tail_setting(f"{PAPER_TAIL}\n{not_a_video}")

    assert tails == {PAPER_TAIL: 1}
    assert rejected == {"are not video post patterns": 1}


def test_reasons_for_rejection_are_counted_separately():
    tails, rejected = SearchTikTokSample.parse_tail_setting("0000001011011111110110\nnot a pattern\n01010")

    assert tails == {}
    assert rejected == {
        "are not video post patterns": 1,
        "could not be read as an ID pattern": 1,
        "look like bit patterns that lost their leading zeros": 1,
    }


# --- narrowing down which patterns to sample with ----------------------------

def test_patterns_are_ordered_by_how_often_they_occurred():
    """
    A query too large for this instance's budget is cut off at the end of the
    list, so the order is what decides which patterns get dropped. Rarest last.
    """
    tails = {"0000000000110100000001": 3, "0000000000110100000010": 50, "0000000000110100000100": 17}

    assert SearchTikTokSample.select_tails(tails) == [
        "0000000000110100000010", "0000000000110100000100", "0000000000110100000001"
    ]


def test_machine_ids_are_ranked_by_their_combined_frequency():
    """
    A machine is as common as all its patterns together, not as its best one.

    Machine 1 here has two middling patterns; machine 2 has one big one. Ranking
    on individual patterns would pick the wrong machine.
    """
    machine_one = ("0000000000110100000001", "0000000001110100000001")
    machine_two = "0000000000110100000010"
    tails = {machine_one[0]: 30, machine_one[1]: 30, machine_two: 40}

    selected = SearchTikTokSample.select_tails(tails, machine_ids=1)

    assert sorted(selected) == sorted(machine_one)


def test_selecting_from_nothing_gives_nothing():
    assert SearchTikTokSample.select_tails({}) == []
    assert SearchTikTokSample.select_tails({PAPER_TAIL: 1}, machine_ids=1) == [PAPER_TAIL]


# --- having nothing to sample with -------------------------------------------

"""
With no configured patterns and no public TikTok datasets, there is nothing to
generate IDs from. Every ID the data source could produce would be one it knows
cannot exist, so it has to refuse rather than spend a query's worth of requests
proving the point. These check that it refuses, and that it says which of the
several ways of having nothing actually happened.
"""


class FakeSeeder:
    """A stand-in for the seeding worker, holding just what `seed()` touches."""

    interrupted = False
    iterate_posts = SeedTikTokSample.iterate_posts
    record_post = staticmethod(SeedTikTokSample.record_post)
    records_per_dataset = staticmethod(SeedTikTokSample.records_per_dataset)
    scan = SeedTikTokSample.scan

    def __init__(self, tmp_path, datasets):
        self.datasets = datasets
        self.config = type("config", (), {"get": staticmethod(
            lambda key, default=None: tmp_path if key == "PATH_DATA" else 250000)})()
        self.db = type("db", (), {"fetchall": staticmethod(lambda *a: self.datasets)})()
        self.log = type("log", (), {"info": staticmethod(lambda *a, **kw: None),
                                    "error": staticmethod(lambda *a, **kw: None)})()


class FakeConfig:
    """Just enough of a configuration reader to find the cache file."""

    db = None

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path

    def get(self, key, default=None):
        return self.tmp_path if key == "PATH_CONFIG" else default


def write_dataset(tmp_path, name, posts):
    """`posts` is a list of post IDs, or of (post ID, location) tuples."""
    posts = [post if type(post) is tuple else (post, None) for post in posts]
    (tmp_path / name).write_text(
        "\n".join(json.dumps({"id": str(post_id), "locationCreated": location} if location else {"id": str(post_id)})
                  for post_id, location in posts), encoding="utf-8")
    return {"key": name, "type": "tiktok-search", "result_file": name}


def test_no_public_datasets_at_all_is_refused():
    tails, machines, posts, datasets, problem = SeedTikTokSample.seed(FakeSeeder(None, []))

    assert tails == {}
    assert problem == NO_PATTERNS_ANYWHERE


def test_datasets_whose_files_are_gone_say_so(tmp_path):
    gone = [{"key": "a", "type": "tiktok-search", "result_file": "deleted.ndjson"},
            {"key": "b", "type": "tiktok-search", "result_file": ""}]

    tails, machines, posts, datasets, problem = SeedTikTokSample.seed(FakeSeeder(tmp_path, gone))

    assert tails == {}
    assert "none of their result files could be read" in problem


def test_datasets_without_video_ids_say_so(tmp_path):
    """A dataset of user or music IDs parses fine but yields no video patterns."""
    music_id = 6788901234567890123
    assert int(f"{music_id:064b}"[52:56], 2) != VIDEO_ENTITY_TYPE
    records = [write_dataset(tmp_path, "music.ndjson", [music_id])]

    tails, machines, posts, datasets, problem = SeedTikTokSample.seed(FakeSeeder(tmp_path, records))

    assert tails == {}
    assert "none of them were video post IDs" in problem


def test_seeding_works_when_there_is_something_to_seed_from(tmp_path):
    records = [write_dataset(tmp_path, "posts.ndjson", [PAPER_ID, OTHER_ID, PAPER_ID])]

    tails, machines, posts, datasets, problem = SeedTikTokSample.seed(FakeSeeder(tmp_path, records))

    assert problem == ""
    assert tails == {PAPER_TAIL: 1, OTHER_TAIL: 1}  # the repeated post counted once
    assert posts == 2
    assert set(machines) == {str(PAPER_MACHINE), str(OTHER_MACHINE)}


# --- matching machine IDs to where their posts were made ---------------------

"""
A machine ID is the datacentre a post was uploaded to, which is not the same
thing as where the post was made - it only correlates with it. So the data
source does not translate machines into regions; it records what each machine's
posts actually said, and lets someone choose from that. These check that what is
recorded is what was in the data, and that a selection follows from what is
shown rather than from the long tail behind it.
"""


def test_locations_are_tallied_per_machine_id(tmp_path):
    records = [write_dataset(tmp_path, "posts.ndjson", [
        (PAPER_ID, "US"),
        (OTHER_ID, "NL"),
        (PAPER_ID + 2 ** 32, "us"),  # a second post from machine 1, one second later
    ])]

    tails, machines, posts, datasets, problem = SeedTikTokSample.seed(FakeSeeder(tmp_path, records))

    assert machines[str(PAPER_MACHINE)] == {"posts": 2, "located": 2, "locations": {"US": 2}}
    assert machines[str(OTHER_MACHINE)] == {"posts": 1, "located": 1, "locations": {"NL": 1}}


def test_posts_without_a_usable_location_still_count(tmp_path):
    """A post with no location is a post that machine minted, just not a located one."""
    records = [write_dataset(tmp_path, "posts.ndjson", [(PAPER_ID, "US"), (PAPER_ID + 2 ** 32, "unknown")])]

    tails, machines, posts, datasets, problem = SeedTikTokSample.seed(FakeSeeder(tmp_path, records))

    assert machines[str(PAPER_MACHINE)] == {"posts": 2, "located": 1, "locations": {"US": 1}}


def test_locations_are_read_from_mapped_csv_exports(tmp_path):
    """NDJSON holds what TikTok returned, CSV holds the mapped version of it."""
    (tmp_path / "posts.csv").write_text(
        f"id,location_created\n{PAPER_ID},US\n{OTHER_ID},JP\n", encoding="utf-8")
    records = [{"key": "a", "type": "tiktok-search", "result_file": "posts.csv"}]

    tails, machines, posts, datasets, problem = SeedTikTokSample.seed(FakeSeeder(tmp_path, records))

    assert machines[str(PAPER_MACHINE)]["locations"] == {"US": 1}
    assert machines[str(OTHER_MACHINE)]["locations"] == {"JP": 1}


def test_no_single_dataset_can_fill_the_cache_on_its_own(tmp_path):
    """
    The newest large dataset must not become the whole picture.

    Reading datasets to exhaustion, newest first, would let one collection
    supply every pattern and every country count - which describes that
    collection rather than the platform, and puts more of what its owner put on
    this server in front of everyone than they had reason to expect.
    """
    machine_one = [PAPER_ID + (second << 32) for second in range(50)]
    machine_two = [OTHER_ID + (second << 32) for second in range(50)]
    records = [write_dataset(tmp_path, "newest.ndjson", machine_one),
               write_dataset(tmp_path, "older.ndjson", machine_two)]

    seeder = FakeSeeder(tmp_path, records)
    seeder.config = type("config", (), {"get": staticmethod(
        lambda key, default=None: tmp_path if key == "PATH_DATA" else 20)})()

    tails, machines, posts, datasets, problem = SeedTikTokSample.seed(seeder)

    # the limit of 20 is split over both datasets rather than taken from the first
    assert datasets == 2
    assert machines[str(PAPER_MACHINE)]["posts"] == 10
    assert machines[str(OTHER_MACHINE)]["posts"] == 10


def test_a_short_cache_is_topped_up_from_wherever_it_can_be(tmp_path):
    """
    Spreading the reads must not cost coverage.

    On a server whose datasets are mostly small, capping every dataset at its
    share would leave the cache a fraction of the size it was asked for - and
    coverage is the whole point of the method, so a second pass takes the rest
    wherever there is more to be had.
    """
    small = [PAPER_ID + (second << 32) for second in range(3)]
    big = [OTHER_ID + (second << 32) for second in range(200)]
    records = [write_dataset(tmp_path, "small.ndjson", small), write_dataset(tmp_path, "big.ndjson", big)]

    seeder = FakeSeeder(tmp_path, records)
    seeder.config = type("config", (), {"get": staticmethod(
        lambda key, default=None: tmp_path if key == "PATH_DATA" else 50)})()

    tails, machines, posts, datasets, problem = SeedTikTokSample.seed(seeder)

    assert posts == 50  # not the 28 the first pass alone would have found
    assert machines[str(PAPER_MACHINE)]["posts"] == 3
    assert machines[str(OTHER_MACHINE)]["posts"] == 47


def test_one_dataset_may_still_fill_the_cache_when_it_is_the_only_one(tmp_path):
    """Spreading the reads matters; half a cache for want of a second dataset does not."""
    assert SeedTikTokSample.records_per_dataset(1000, 1) == 1000
    assert SeedTikTokSample.records_per_dataset(1000, 4) == 250
    assert SeedTikTokSample.records_per_dataset(1000, 400) == 100


def write_cache(tmp_path, machines, version=3):
    (tmp_path / TAIL_CACHE_FILE).write_text(json.dumps({
        "version": version, "created": 0, "posts_scanned": 1000, "datasets_scanned": 2,
        "tails": {PAPER_TAIL: 1000}, "machines": machines
    }), encoding="utf-8")


def test_every_country_a_machine_saw_is_kept(tmp_path):
    """
    The cache keeps whatever the posts said; the query form is where the list
    gets shortened. Filtering here instead would mean a country someone was
    never shown could still be behind a machine they select.
    """
    seen = {"US": 900, "NL": 3, "GB": 40, "JP": 12, "DE": 8, "FR": 2}
    write_cache(tmp_path, {str(PAPER_MACHINE): {"posts": 1000, "located": 965, "locations": seen}})

    machines = SearchTikTokSample.get_machines(FakeConfig(tmp_path))

    assert machines[PAPER_MACHINE]["locations"] == seen
    assert machines[PAPER_MACHINE]["located"] == 965


def test_only_the_most_common_countries_are_listed_per_machine(tmp_path):
    """Five is enough to characterise a machine; the tail behind it is noise in a form."""
    seen = {"US": 900, "NL": 3, "GB": 40, "JP": 12, "DE": 8, "FR": 2}
    write_cache(tmp_path, {str(PAPER_MACHINE): {"posts": 1000, "located": 965, "locations": seen}})

    machine = SearchTikTokSample.get_machines(FakeConfig(tmp_path))[PAPER_MACHINE]

    assert SearchTikTokSample.machine_locations(machine) == ["US", "GB", "JP", "DE", "NL"]
    assert SearchTikTokSample.describe_locations(machine["locations"]).count("(") == 5


def test_older_caches_are_read_for_what_they_do_have(tmp_path):
    """A cache from before `located` was recorded still has the counts it was the total of."""
    (tmp_path / TAIL_CACHE_FILE).write_text(json.dumps({
        "version": 2, "created": 0, "posts_scanned": 100, "datasets_scanned": 1,
        "tails": {PAPER_TAIL: 100},
        "machines": {str(PAPER_MACHINE): {"posts": 100, "locations": {"US": 40}}}
    }), encoding="utf-8")

    machines = SearchTikTokSample.get_machines(FakeConfig(tmp_path))

    assert machines[PAPER_MACHINE] == {"posts": 100, "located": 40, "locations": {"US": 40}}


def test_a_machines_locations_are_described_as_shares():
    described = SearchTikTokSample.describe_locations({"US": 50, "NL": 10, "GB": 5, "DE": 4, "FR": 3, "BE": 28})

    assert described == "US (50%), BE (28%), NL (10%), GB (5%) and DE (4%)"  # FR falls outside the cut-off


def test_a_share_too_small_to_round_is_not_shown_as_zero():
    assert SearchTikTokSample.describe_locations({"US": 1000, "NL": 1}) == "US (100%) and NL (<1%)"


def test_selecting_a_location_selects_what_was_shown_for_it():
    """
    The countries named for a machine are the ones that select it.

    A machine posts from everywhere, so its location counts have a long tail.
    Selecting a country from that tail would pick up machines the query form
    never associated with it, which is a sample nobody asked for.
    """
    machines = {
        1: {"posts": 100, "locations": {"US": 60, "NL": 40}},
        2: {"posts": 100, "locations": {"JP": 99, "US": 1}},
    }
    tails = {PAPER_TAIL: 1}

    assert SearchTikTokSample.machine_locations(machines[2], limit=1) == ["JP"]

    selected, problem = SearchTikTokSample.resolve_machines(
        {"machine_id_mode": "location", "machine_id_locations": ["NL"]}, tails, machines)

    assert selected == {1}


def test_selecting_a_location_that_matches_nothing_is_refused():
    machines = {1: {"posts": 10, "locations": {"US": 10}}}

    selected, problem = SearchTikTokSample.resolve_machines(
        {"machine_id_mode": "location", "machine_id_locations": ["NL"]}, {PAPER_TAIL: 1}, machines)

    assert selected == set()
    assert "No machine IDs are associated with NL" in problem


# --- writing machine IDs by hand ---------------------------------------------


def test_machine_ids_can_be_written_as_bits_or_as_numbers():
    machines, rejected = SearchTikTokSample.parse_machine_ids("000101\n5, 46\n101110")

    assert machines == {5, 46}
    assert rejected == []


def test_machine_ids_that_cannot_exist_are_refused():
    machines, rejected = SearchTikTokSample.parse_machine_ids("64, 5, nonsense, 0101010")

    assert machines == {5}
    assert rejected == ["64", "nonsense", "0101010"]


def tail_for_machine(machine, counter=0):
    """A video post pattern minted by a given machine."""
    return f"{counter:010b}" + f"{VIDEO_ENTITY_TYPE:04b}" + "00" + f"{machine:06b}"


def test_the_most_common_dropdown_stops_before_it_repeats_all():
    """
    There is one option per machine ID found, and no more.

    Offering an option for every machine there is would end in one that selects
    exactly what 'all' selects. And on an instance where every machine posts
    from the same country - which is most of them - naming countries alone
    would give a list of options that all read the same, so each says what
    share of the known posts it covers as well.
    """
    tails = {tail_for_machine(1): 60, tail_for_machine(2): 30, tail_for_machine(3): 10}
    machines = {machine: {"posts": 10, "locations": {"US": 10}} for machine in (1, 2, 3)}

    options = SearchTikTokSample.get_common_machine_options(tails, machines)

    assert list(options) == ["0", "1", "2"]
    assert "60% of known posts" in options["1"]
    assert "90% of known posts" in options["2"]
    assert len(set(options.values())) == len(options)


def test_the_machine_id_modes_narrow_down_the_patterns_they_say_they_do():
    machine_one = "0000000000110100000001"
    machine_two = "0000000000110100000010"
    tails = {machine_one: 30, machine_two: 40}

    assert SearchTikTokSample.select_tails(tails, machines={1}) == [machine_one]
    assert SearchTikTokSample.resolve_machines({"machine_id_mode": "all"}, tails, {})[0] is None
    assert SearchTikTokSample.resolve_machines({"machine_id_mode": "common", "machine_id_count": 1}, tails, {})[0] == {2}
    assert SearchTikTokSample.resolve_machines(
        {"machine_id_mode": "custom", "machine_id_custom": "000001"}, tails, {})[0] == {1}


# --- leaving out the rarest patterns -----------------------------------------

"""
Every ID pattern costs the same number of requests per second sampled, but the
rarest ones almost never yield a post. Dropping them buys hit rate and pays in
coverage, which is the one thing this method exists to provide - so the
arithmetic behind the trade has to be right, and the form has to state it.
"""


def test_coverage_takes_the_most_common_patterns_until_the_target_is_met():
    tails = {"a": 60, "b": 30, "c": 8, "d": 2}

    assert SearchTikTokSample.select_tails(tails, coverage=100) == ["a", "b", "c", "d"]
    assert SearchTikTokSample.select_tails(tails, coverage=90) == ["a", "b"]
    assert SearchTikTokSample.select_tails(tails, coverage=60) == ["a"]


def test_a_coverage_target_is_never_undershot():
    """98% has to mean at least 98%, so a pattern straddling the line is kept."""
    tails = {"a": 97, "b": 2, "c": 1}

    kept = SearchTikTokSample.select_tails(tails, coverage=98)

    assert kept == ["a", "b"]
    assert sum(tails[t] for t in kept) / sum(tails.values()) >= 0.98


def test_coverage_is_of_the_machine_ids_actually_selected():
    """
    Asking for 90% of a region's posting must not silently mean 90% of the
    platform's, which on a narrow machine selection is a different number.
    """
    one, two = "0000000000110100000001", "0000000000110100000010"
    rare_one = "0000000100110100000001"
    tails = {one: 50, rare_one: 5, two: 945}

    # of machine 1's 55 posts, `one` alone is 91%
    assert SearchTikTokSample.select_tails(tails, machines={1}, coverage=90) == [one]


def test_targets_that_come_out_the_same_are_offered_once():
    """A thin cache must not offer eight options that all do the same thing."""
    options = SearchTikTokSample.get_pattern_options({"a": 100, "b": 100})

    assert list(options) == ["100"]


def test_the_pattern_limit_is_not_offered_when_there_is_nothing_to_choose():
    assert SearchTikTokSample.get_pattern_limit_option({"a": 1}) == {}
    assert SearchTikTokSample.get_pattern_limit_option({}) == {}


def test_the_options_say_what_is_given_up_and_what_is_bought():
    tails = {f"{i:022b}": (100 if i < 10 else 1) for i in range(30)}

    options = SearchTikTokSample.get_pattern_options(tails)

    assert options["100"] == "all 30/30 (100%)"
    assert len(options) <= 10
    for value, label in options.items():
        if value != "100":
            assert "of posts" in label and "hit rate" in label


def test_an_unreadable_coverage_falls_back_to_sampling_everything():
    """The safe direction is more coverage, not less."""
    for value in (None, "", "nonsense", -5):
        assert SearchTikTokSample.parse_coverage(value) in (100.0, 0.0)

    assert SearchTikTokSample.parse_coverage("99.5") == 99.5
    assert SearchTikTokSample.parse_coverage(None) == 100.0
    assert SearchTikTokSample.parse_coverage(150) == 100.0


def test_the_two_limits_multiply_rather_than_compete():
    """
    Machine IDs narrow which patterns exist; coverage then trims the rarest of
    those. Applied the other way round, or to the wrong denominator, "99% of a
    region" would quietly mean 99% of the platform and drop most of the region.
    """
    one, two = "0000000000110100000001", "0000000000110100000010"
    rare_one, rare_two = "0000000100110100000001", "0000000100110100000010"
    tails = {one: 500, rare_one: 5, two: 490, rare_two: 5}

    everything = SearchTikTokSample.select_tails(tails)
    trimmed = SearchTikTokSample.select_tails(tails, coverage=99)
    one_machine = SearchTikTokSample.select_tails(tails, machines={1})
    both = SearchTikTokSample.select_tails(tails, machines={1}, coverage=99)

    assert len(everything) == 4
    assert sorted(trimmed) == sorted([one, two])       # the two rare patterns go
    assert sorted(one_machine) == sorted([one, rare_one])
    assert both == [one]                               # 500 of machine 1's 505 posts is 99%

    # the share of all posts kept is the product of the two limits, near enough
    kept = sum(tails[t] for t in both) / sum(tails.values())
    assert 0.49 < kept < 0.51
