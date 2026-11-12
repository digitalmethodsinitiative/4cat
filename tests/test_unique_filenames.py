"""
Tests for `UniqueFilenames` and `deduplicate_filename`.

Processors that write a file per item have to make sure two items cannot claim
the same name: the second write destroys the first file, and whatever the
archive's metadata said about it. The scenarios below are the ones that bit
real processors.
"""
import pytest

from common.lib.helpers import UniqueFilenames, deduplicate_filename, fold_filename, url_to_filename


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


def test_deduplicate_filename_rejects_a_non_set():
	with pytest.raises(TypeError):
		deduplicate_filename("clip.wav", existing_filenames_folded=["clip.wav"])


def test_deduplicate_filename_respects_max_bytes():
	name = deduplicate_filename("a" * 300 + ".wav", max_bytes=32)
	assert len(name.encode("utf-8")) <= 32
	assert name.endswith(".wav")


def test_deduplicate_filename_keeps_the_index_within_max_bytes():
	seen = set()
	for _ in range(3):
		name = deduplicate_filename("a" * 300 + ".wav", existing_filenames_folded=seen, max_bytes=32)
		seen.add(fold_filename(name))
	assert len(seen) == 3
	assert all(len(name.encode("utf-8")) <= 32 for name in seen)


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


def test_the_german_sharp_s_matches_its_two_letter_spelling(tmp_path):
	"""
	Lower-casing leaves the sharp s as it is, so seeing that these are one name
	takes case folding rather than lower-casing.
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
