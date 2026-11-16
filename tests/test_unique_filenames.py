"""
Tests for `UniqueFilenames` and `deduplicate_filename`.

Processors that write a file per item have to make sure two items cannot claim
the same name: the second write destroys the first file, and whatever the
archive's metadata said about it. The scenarios below are the ones that bit
real processors.
"""
import pytest

from common.lib.helpers import (UniqueFilenames, deduplicate_filename, filename_to_prefix,
                                fold_filename, url_to_filename)


def test_free_name_is_returned_unchanged(tmp_path):
	assert UniqueFilenames(tmp_path).reserve("clip.wav") == "clip.wav"


def test_videos_sharing_a_stem_get_different_audio_names(tmp_path):
	"""
	The audio extractor: `clip.mp4` and `clip.webm` both suggest `clip.wav`. If
	they got the same name the second extraction would overwrite the first
	file, replace its metadata entry, and - because a file by that name then
	exists - be counted as a success even when ffmpeg failed.
	"""
	names = UniqueFilenames(tmp_path)
	first = names.reserve("clip.wav")
	second = names.reserve("clip.wav")
	third = names.reserve("clip.wav")

	assert first == "clip.wav"
	assert len({first, second, third}) == 3
	assert all(name.endswith(".wav") for name in (first, second, third))


def test_extensionless_names_work_for_folders(tmp_path):
	"""
	The frame extractor names a *folder* per video, so the name has no
	extension. `url_to_filename` cannot serve this: with no dot it falls back
	to its default name entirely.
	"""
	names = UniqueFilenames(tmp_path)
	assert names.reserve("clip") == "clip"
	assert names.reserve("clip") == "clip-1"
	# which is exactly why this does not go through url_to_filename
	assert url_to_filename("clip", default_name="file", default_ext=".png") == "file.png"


def test_files_already_in_the_directory_are_taken(tmp_path):
	tmp_path.joinpath("clip.wav").touch()
	tmp_path.joinpath("notes.txt").touch()
	names = UniqueFilenames(tmp_path)
	assert names.reserve("clip.wav") != "clip.wav"
	assert names.reserve("notes.txt") != "notes.txt"
	assert names.reserve("other.wav") == "other.wav"


def test_a_file_written_behind_our_back_is_taken(tmp_path):
	"""
	Not every file in the directory was asked for here: yt-dlp names its own
	downloads, and a video copied out of an earlier archive keeps the name it
	had there. Every name handed out is checked against the directory as well,
	so a file nobody reserved cannot be handed out on top of.
	"""
	names = UniqueFilenames(tmp_path)
	assert names.reserve("clip.wav") == "clip.wav"
	# something else writes the file we just handed out, plus one we never saw
	tmp_path.joinpath("clip.wav").touch()
	tmp_path.joinpath("late.wav").touch()

	assert names.reserve("clip.wav") == "clip-1.wav"
	assert names.reserve("late.wav") != "late.wav"


def test_a_reserved_name_is_taken_before_its_file_exists(tmp_path):
	"""
	A reservation counts from the moment it is made, so a name has to be
	reserved before it is written rather than relying on the file being there.
	"""
	names = UniqueFilenames(tmp_path)
	assert names.reserve("clip.wav") == "clip.wav"
	assert not tmp_path.joinpath("clip.wav").exists()
	assert names.reserve("clip.wav") == "clip-1.wav"


def test_missing_directory_is_fine(tmp_path):
	names = UniqueFilenames(tmp_path.joinpath("does-not-exist"))
	assert names.reserve("clip.wav") == "clip.wav"
	assert names.reserve("clip.wav") == "clip-1.wav"


def test_reserve_for_url_derives_and_reserves(tmp_path):
	names = UniqueFilenames(tmp_path)
	assert names.reserve_for_url("https://example.com/a/photo.png") == "photo.png"
	# a different URL with the same last path segment cannot take the same name
	assert names.reserve_for_url("https://example.com/b/photo.png") == "photo-1.png"
	# no filename in the URL at all
	assert names.reserve_for_url("https://example.com/", default_name="file",
								 default_ext=".png") == "file.png"


def test_replace_frees_the_old_name(tmp_path):
	"""
	The image downloader corrects an extension after download, so the name it
	gives up has to become available again rather than stay blocked.
	"""
	names = UniqueFilenames(tmp_path)
	names.reserve("photo.png")
	assert names.replace("photo.png", "photo.jpeg") == "photo.jpeg"
	# the name it gave up is free for someone else now
	assert names.reserve("photo.png") == "photo.png"


def test_replace_avoids_a_name_another_file_has(tmp_path):
	"""
	Two URLs whose files both turn out to be JPEG: `photo.png` and `photo.jpg`
	both want `photo.jpeg`, and only one can have it.
	"""
	names = UniqueFilenames(tmp_path)
	names.reserve("photo.png")
	names.reserve("photo.jpg")

	first = names.replace("photo.png", "photo.jpeg")
	second = names.replace("photo.jpg", "photo.jpeg")

	assert first == "photo.jpeg"
	assert second == "photo-1.jpeg"


def test_claiming_one_name_twice_counts_it_once(tmp_path):
	"""
	yt-dlp reports a file once per postprocessor that runs on it, so the same
	name is claimed more than once. Counting it twice would mean it had to be
	given up twice before it was free again.
	"""
	names = UniqueFilenames(tmp_path)
	names.claim("video.mp4")
	names.claim("video.mp4")

	names.replace("video.mp4", "video.webm")

	assert names.reserve("video.mp4") == "video.mp4"


def test_giving_up_a_name_it_never_handed_out_frees_nothing(tmp_path):
	"""
	This is why the names are kept as they were handed out as well as reduced.
	`A.mp4` and `a.mp4` reduce to one text, so without the names themselves,
	giving up the first would free the text the second still holds.
	"""
	names = UniqueFilenames(tmp_path)
	names.claim("a.mp4")

	names.replace("A.mp4", "unrelated.png")

	assert names.reserve("a.mp4") == "a-1.mp4"


def test_a_name_given_up_stays_taken_while_another_reduces_to_it(tmp_path):
	"""
	Two names can reduce to the same text, which the downloaders can both hold
	at once because `claim` takes a name as it is. Giving one up must leave the
	other's name taken, or a later file could be handed a name that unpacks
	onto it on Windows.
	"""
	names = UniqueFilenames(tmp_path)
	names.claim("Photo.png")
	names.claim("photo.png")

	names.replace("Photo.png", "something.jpeg")

	assert names.reserve("photo.png") == "photo-1.png"


def test_claim_records_a_name_chosen_elsewhere(tmp_path):
	"""
	The video downloader has three things writing into one folder: files copied
	out of an earlier archive keep the name they had there, and yt-dlp names
	its own downloads. Neither asks first, so they are claimed afterwards.
	"""
	names = UniqueFilenames(tmp_path)
	names.claim("copied-from-an-earlier-run.mp4")
	names.claim("some_url_00001.mp4")

	assert names.reserve("copied-from-an-earlier-run.mp4") == "copied-from-an-earlier-run-1.mp4"
	assert names.reserve_for_url("https://example.com/some_url_00001.mp4") == "some_url_00001-1.mp4"


def test_long_urls_sharing_a_slug_prefix_get_different_names(tmp_path):
	"""
	The video downloader builds yt-dlp's output template from the URL
	slugified and cut to 100 characters, so two long URLs that differ only
	near the end would otherwise be given the same template.
	"""
	names = UniqueFilenames(tmp_path)
	slug = "a" * 100
	assert names.reserve(slug) == slug
	assert names.reserve(slug) == f"{slug}-1"


def test_deduplicate_filename_rejects_a_list_of_names():
	"""A list is checked name by name, which in a loop over an archive is slow"""
	with pytest.raises(TypeError):
		deduplicate_filename("clip.wav", existing_filenames_folded=["clip.wav"])


def test_deduplicate_filename_takes_names_as_the_keys_of_a_dict():
	"""Which is how `UniqueFilenames` holds them, with the names against each"""
	taken = {fold_filename("clip.wav"): ["clip.wav"]}

	assert deduplicate_filename("clip.wav", existing_filenames_folded=taken) == "clip-1.wav"


def test_deduplicate_filename_respects_max_bytes():
	name = deduplicate_filename("a" * 300 + ".wav", max_bytes=32)
	assert len(name.encode("utf-8")) <= 32
	assert name.endswith(".wav")


def test_deduplicate_filename_keeps_the_index_within_max_bytes():
	# the names as they come back, since it is those that have to fit: folding
	# one can shorten it, so measuring the folded names would measure nothing
	names = []
	seen = set()
	for _ in range(3):
		name = deduplicate_filename("a" * 300 + ".wav", existing_filenames_folded=seen, max_bytes=32)
		names.append(name)
		seen.add(fold_filename(name))
	assert len(seen) == 3
	assert all(len(name.encode("utf-8")) <= 32 for name in names)


"""
Names that are one name to some file systems.

4CAT writes an archive on the server and the researcher unpacks it on their
own machine. Windows and macOS see two names as one in ways Linux does not, so
a name that looks free on the server can land on a file that is already there
once the archive is opened: it unpacks short, with nothing to say so. A name is
free here only when no name already taken reduces to the same text.
"""


def test_names_differing_only_in_capitals_are_not_both_free(tmp_path):
	names = UniqueFilenames(tmp_path)

	assert names.reserve("A.mp4") == "A.mp4"
	assert names.reserve("a.mp4") == "a-1.mp4"


def test_the_name_handed_out_keeps_its_own_capitals(tmp_path):
	"""Only the comparing is done on a reduced name; the caller gets what it asked for"""
	assert UniqueFilenames(tmp_path).reserve("Clip.MP4") == "Clip.MP4"


def test_a_file_on_disk_differing_only_in_capitals_is_taken(tmp_path):
	"""The file in the way need not have been named from here"""
	tmp_path.joinpath("Clip.wav").touch()

	assert UniqueFilenames(tmp_path).reserve("clip.wav") == "clip-1.wav"


def test_a_claimed_name_differing_only_in_capitals_is_taken(tmp_path):
	names = UniqueFilenames(tmp_path)
	names.claim("Some_URL_00001.mp4")

	assert names.reserve_for_url("https://example.com/some_url_00001.mp4") == "some_url_00001-1.mp4"


def test_the_german_sharp_s_is_treated_as_its_two_letter_spelling(tmp_path):
	"""
	Case folding makes these one name. No file system agrees, so this is
	stricter than it needs to be: it costs the second one a `-1` it could have
	done without, and it is recorded here so the behaviour is not a surprise.
	"""
	names = UniqueFilenames(tmp_path)

	assert names.reserve("stra\u00dfe.mp4") == "stra\u00dfe.mp4"
	assert names.reserve("STRASSE.mp4") == "STRASSE-1.mp4"


def test_an_accent_written_two_ways_is_one_name(tmp_path):
	"""
	macOS stores an accented letter as the plain letter followed by the accent,
	and treats the single-character spelling as the same file.

	The two names below are written as escapes on purpose. Spelled out they
	look exactly alike, and a reader tidying them into the characters they
	stand for would leave a test that no longer tests anything.
	"""
	names = UniqueFilenames(tmp_path)
	one_character = "caf\u00e9.mp4"
	letter_then_accent = "cafe\u0301.mp4"

	assert names.reserve(one_character) == one_character
	assert names.reserve(letter_then_accent) != letter_then_accent


def test_a_dot_or_space_at_the_end_does_not_make_a_new_name(tmp_path):
	"""Windows drops dots and spaces at the end of a name, so these are all `clip` there"""
	names = UniqueFilenames(tmp_path)

	assert names.reserve("clip") == "clip"
	assert names.reserve("clip.") != "clip."
	assert names.reserve("clip ") != "clip "


def test_reducing_a_name_is_not_a_way_to_write_it(tmp_path):
	"""
	The reduced name is for comparing. A caller that wrote a file under it would
	undo the point of the exercise, so this records what it is.
	"""
	assert fold_filename("Clip.MP4") == "clip.mp4"
	assert fold_filename("clip. ") == "clip"

"""
Building a name out of another file's name.

A file made from another file is named after it, so that the two can be told
apart by eye. What comes out has to be a name a file system will take, and two
videos that are not the same video should not lead to one name.
"""


def test_the_extension_becomes_part_of_the_name():
	"""So that a frame of `clip.mp4` is not called `clip.mp4_frame_1.jpeg`"""
	assert filename_to_prefix("clip.mp4") == "clip_mp4"


def test_only_the_last_dot_changes():
	"""
	Replacing every dot would give `my_video_mp4` for both of these, and they
	are two different videos.
	"""
	assert filename_to_prefix("my.video.mp4") == "my.video_mp4"
	assert filename_to_prefix("my_video.mp4") == "my_video_mp4"


def test_a_name_without_an_extension_is_left_alone():
	assert filename_to_prefix("clip") == "clip"


def test_characters_windows_forbids_are_replaced():
	"""A file by this name cannot be written on Windows at all"""
	for forbidden in (":", "?", "*", "\"", "<", ">", "|", "/", "\\"):
		assert not set(forbidden) & set(filename_to_prefix(f"what{forbidden}.mp4"))


def test_dots_and_spaces_at_the_ends_are_dropped():
	"""
	Windows drops a dot at the end of a name, and a name starting with one is
	hidden from whoever unpacks the archive.
	"""
	assert filename_to_prefix("clip.") == "clip"
	assert filename_to_prefix("clip ") == "clip"
	assert filename_to_prefix(".clip.mp4") == "clip_mp4"


def test_a_name_with_nothing_usable_left_falls_back():
	assert filename_to_prefix("...") == "file"
	assert filename_to_prefix("...", fallback="video") == "video"


def test_two_names_that_still_meet_are_kept_apart_by_the_registry(tmp_path):
	"""
	The one pair this cannot keep apart, and what happens to it. Nothing is
	lost: the names differ, and which video each came from is in the metadata.
	"""
	assert filename_to_prefix("a.mp4") == filename_to_prefix("a_mp4") == "a_mp4"

	names = UniqueFilenames()
	assert names.reserve(filename_to_prefix("a.mp4")) == "a_mp4"
	assert names.reserve(filename_to_prefix("a_mp4")) == "a_mp4-1"


"""
Reserving the start of a name.

A name built from another file's name is one piece: any dot left in it came
from the source file and is not an extension. It is also not a file name
itself, since the caller adds to it, so it is reserved with room for whatever
the caller will add.
"""


def test_an_index_goes_at_the_end_of_a_name_with_no_extension():
	"""
	Left to itself, `deduplicate_filename` would read `my.video_mp4` as a name
	`my` with an extension `.video_mp4` and hand back `my-1.video_mp4`.
	"""
	taken = {fold_filename("my.video_mp4")}

	assert deduplicate_filename("my.video_mp4", existing_filenames_folded=taken,
								has_extension=False) == "my.video_mp4-1"


def test_shortening_a_name_with_no_extension_keeps_its_start():
	"""
	Nothing is held back as an extension, so what is dropped is the end of the
	name rather than the beginning of it.
	"""
	name = deduplicate_filename("2026.01.15." + "a" * 300, max_bytes=32, has_extension=False)

	assert name.startswith("2026.01.15.")
	assert len(name.encode("utf-8")) == 32


def test_reserve_prefix_builds_the_name_and_reserves_it(tmp_path):
	names = UniqueFilenames(tmp_path)

	assert names.reserve_prefix("clip.mp4") == "clip_mp4"
	assert names.reserve_prefix("clip.mp4") == "clip_mp4-1"


def test_reserve_prefix_leaves_room_for_what_the_caller_adds(tmp_path):
	"""
	A video's name can be 255 bytes, the longest a file name may be, so
	anything named after it needs the name shortened first. The frame
	extractor builds three names from it: a frame and the two ffmpeg logs. It
	has to ask room for the longest of them.
	"""
	built = ("_frame_0000001.jpeg", "_ffmpeg_output.log", "_ffmpeg_error.log")
	video = "v" * 251 + ".mp4"

	prefix = UniqueFilenames(tmp_path).reserve_prefix(video, adds=max(built, key=len))

	assert all(len((prefix + suffix).encode("utf-8")) <= 255 for suffix in built)


def test_reserve_prefix_keeps_apart_two_videos_whose_names_meet(tmp_path):
	"""The pair `filename_to_prefix` cannot keep apart, reserved the usual way"""
	names = UniqueFilenames(tmp_path)

	assert names.reserve_prefix("a.mp4") == "a_mp4"
	assert names.reserve_prefix("a_mp4") == "a_mp4-1"


def test_reserve_prefix_tells_apart_videos_sharing_a_stem(tmp_path):
	"""
	What the audio extractor and the video hasher need: `clip.mp4` and
	`clip.webm` are one stem, so naming their output after the stem gave the
	second one a `-1` and no way to tell which video it came from.
	"""
	names = UniqueFilenames(tmp_path)

	first = names.reserve_prefix("clip.mp4", adds=".wav")
	second = names.reserve_prefix("clip.webm", adds=".wav")

	assert [f"{first}.wav", f"{second}.wav"] == ["clip_mp4.wav", "clip_webm.wav"]


def test_a_name_of_nothing_but_dots_is_not_handed_back(tmp_path):
	"""
	Windows strips dots and spaces from the end of a name, so a name made only
	of those is no name at all there. A zip member can be called this.
	"""
	assert UniqueFilenames(tmp_path).reserve("...") == "file"
	assert deduplicate_filename("   ", fallback_name="image", fallback_ext=".png") == "image.png"


def test_characters_windows_forbids_include_control_characters():
	"""A zero byte stops Python's own file calls before any file system sees it"""
	assert filename_to_prefix("a\x00b.mp4") == "a_b_mp4"
	assert filename_to_prefix("line\nbreak.mp4") == "line_break_mp4"
