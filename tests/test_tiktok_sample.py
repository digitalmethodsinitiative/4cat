import json

import pytest

from datasources.tiktok_sample.search_tiktok_sample import (SearchTikTokSample, TAIL_LENGTH, VIDEO_ENTITY_TYPE,
                                                            TAIL_MACHINE_SLICE, NO_PATTERNS_ANYWHERE)


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
    """Dropping patterns has to drop the rarest ones, not an arbitrary subset."""
    tails = {"0000000000110100000001": 3, "0000000000110100000010": 50, "0000000000110100000100": 17}

    assert SearchTikTokSample.select_tails(tails) == [
        "0000000000110100000010", "0000000000110100000100", "0000000000110100000001"
    ]
    assert SearchTikTokSample.select_tails(tails, max_patterns=2) == [
        "0000000000110100000010", "0000000000110100000100"
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
    """A stand-in for the worker, holding just what `seed_tails` touches."""

    interrupted = False
    iterate_post_ids = staticmethod(SearchTikTokSample.iterate_post_ids)

    def __init__(self, tmp_path, datasets):
        self.datasets = datasets
        self.config = type("config", (), {"get": staticmethod(
            lambda key, default=None: tmp_path if key == "PATH_DATA" else 250000)})()
        self.db = type("db", (), {"fetchall": staticmethod(lambda *a: self.datasets)})()
        self.dataset = type("dataset", (), {"update_status": staticmethod(lambda *a, **kw: None),
                                            "log": staticmethod(lambda *a, **kw: None)})()
        self.cached = None

    def save_tail_cache(self, tails, posts, datasets):
        self.cached = tails


def write_dataset(tmp_path, name, post_ids):
    (tmp_path / name).write_text("\n".join(json.dumps({"id": str(i)}) for i in post_ids), encoding="utf-8")
    return {"key": name, "type": "tiktok-search", "result_file": name}


def test_no_public_datasets_at_all_is_refused():
    tails, problem = SearchTikTokSample.seed_tails(FakeSeeder(None, []))

    assert tails == {}
    assert problem == NO_PATTERNS_ANYWHERE


def test_datasets_whose_files_are_gone_say_so(tmp_path):
    gone = [{"key": "a", "type": "tiktok-search", "result_file": "deleted.ndjson"},
            {"key": "b", "type": "tiktok-search", "result_file": ""}]

    tails, problem = SearchTikTokSample.seed_tails(FakeSeeder(tmp_path, gone))

    assert tails == {}
    assert "none of their result files could be read" in problem


def test_datasets_without_video_ids_say_so(tmp_path):
    """A dataset of user or music IDs parses fine but yields no video patterns."""
    music_id = 6788901234567890123
    assert int(f"{music_id:064b}"[52:56], 2) != VIDEO_ENTITY_TYPE
    records = [write_dataset(tmp_path, "music.ndjson", [music_id])]

    tails, problem = SearchTikTokSample.seed_tails(FakeSeeder(tmp_path, records))

    assert tails == {}
    assert "none of them were video post IDs" in problem


def test_seeding_works_when_there_is_something_to_seed_from(tmp_path):
    records = [write_dataset(tmp_path, "posts.ndjson", [PAPER_ID, OTHER_ID, PAPER_ID])]
    seeder = FakeSeeder(tmp_path, records)

    tails, problem = SearchTikTokSample.seed_tails(seeder)

    assert problem == ""
    assert tails == {PAPER_TAIL: 1, OTHER_TAIL: 1}  # the repeated post counted once
    assert seeder.cached == tails
