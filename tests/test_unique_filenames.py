"""
Tests for `UniqueFilenames` and `deduplicate_filename`.

Processors that write a file per item have to make sure two items cannot claim
the same name: the second write destroys the first file, and whatever the
archive's metadata said about it. The scenarios below are the ones that bit
real processors.
"""
import pytest

from common.lib.helpers import UniqueFilenames, deduplicate_filename, url_to_filename


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


def test_directory_is_read_once_not_per_name(tmp_path):
	"""
	Reserving is in-memory after construction, so a name must be reserved
	before the file is written rather than relying on the file being there.
	"""
	names = UniqueFilenames(tmp_path)
	assert names.reserve("clip.wav") == "clip.wav"
	# something else writes the file we just handed out, plus another
	tmp_path.joinpath("clip.wav").touch()
	tmp_path.joinpath("late.wav").touch()
	# the one we reserved is still known, the one written behind our back is not
	assert names.reserve("clip.wav") == "clip-1.wav"
	assert names.reserve("late.wav") == "late.wav"


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


def test_deduplicate_filename_rejects_a_non_set():
	with pytest.raises(TypeError):
		deduplicate_filename("clip.wav", existing_filenames=["clip.wav"])


def test_deduplicate_filename_respects_max_bytes():
	name = deduplicate_filename("a" * 300 + ".wav", max_bytes=32)
	assert len(name.encode("utf-8")) <= 32
	assert name.endswith(".wav")


def test_deduplicate_filename_keeps_the_index_within_max_bytes():
	seen = set()
	for _ in range(3):
		name = deduplicate_filename("a" * 300 + ".wav", existing_filenames=seen, max_bytes=32)
		seen.add(name)
	assert len(seen) == 3
	assert all(len(name.encode("utf-8")) <= 32 for name in seen)
