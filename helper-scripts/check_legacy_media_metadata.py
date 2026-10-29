"""
Check how old-format media metadata files would convert to the current format

Media archives (image, video and audio downloads and the like) contain a
.metadata.json file. Files made before the current format (schema version 1)
are converted when they are read. This script tries that conversion for every
archive and reports, per archive, what it would drop or change, so you can
judge whether converting the files on disk would be safe, and where the
conversion could be improved.

The script only reads. It runs SELECT queries on the database, opens archives
for reading, and reads nothing from them but the list of files and
.metadata.json. Nothing is converted on disk.

Output, in the current folder unless --out says otherwise:
- <name>.csv: one row per archive, with what was found
- <name>-details.json: examples of every finding, per archive
- a summary on screen: by processor type, by year, and by finding

The database connection and the data folder are read from config/config.ini
in the 4CAT folder the script is run from. --data-folder overrides the data
folder, e.g. when running from another copy of 4CAT than the one that made
the datasets.

Usage (from the 4CAT root folder, e.g. inside the backend container):
  python3 helper-scripts/check_legacy_media_metadata.py
  python3 helper-scripts/check_legacy_media_metadata.py -k <dataset key>
  python3 helper-scripts/check_legacy_media_metadata.py -f some_archive.zip
  python3 helper-scripts/check_legacy_media_metadata.py --data-folder /mnt/4cat/data
"""
import argparse
import collections
import csv
import datetime
import json
import os
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")

from common.lib.archive_metadata import MediaArchiveMetadata

try:
	from common.lib.archive_metadata import is_support_file
except ImportError:
	# versions of 4CAT before support files were defined in one place
	def is_support_file(filename):
		name = filename.split("/")[-1]
		return name in (".metadata.json", ".token_metadata.json", ".model_metadata.json", "video_archive") \
			or name.endswith(".log")

METADATA_FILENAME = ".metadata.json"

# What each finding means, in the report
FINDINGS = {
	"entry_not_a_record": "an entry is not a record (not a JSON object) and is dropped",
	"entry_without_file_dropped": "an entry marked successful names no file and is dropped",
	"unflagged_entry_as_failure": "an entry without a 'success' flag names no file, so it becomes a failure",
	"ids_as_post_ids": "uses 'ids' (screenshot processors) for the post IDs",
	"post_ids_as_text": "the post IDs are one text with commas, which is split",
	"original_key_kept": "the entry's key is not its URL, file name or post ID, and is kept as 'original_key'",
	"copied_entry_source_ignored": "an entry copied from an earlier archive names another source dataset; "
								   "it is not used",
	"file_not_a_record": "an item in a 'files' list is not a record and is dropped",
	"file_without_filename_dropped": "an item in a 'files' list names no file and is dropped",
	"single_post_id": "uses 'post_id' (one ID) instead of 'post_ids'",
	"no_post_ids": "an entry has no post IDs at all",
	"blank_post_ids_dropped": "empty post IDs are dropped",
	"numeric_post_ids": "post IDs that are numbers become text",
	"url_taken_from_key": "the URL is taken from the entry's key",
	"source_dataset_renamed": "'source_dataset' is read as 'from_dataset'",
	"several_source_datasets": "entries name different source datasets; only the last is kept",
	"failed_url_with_files": "a URL marked as failed lists files; the files are kept as items",
	"retry_false_as_not_a_video": "'retry: false' is read as reason 'not_a_video'",
	"failure_without_reason": "a failure has no reason; 'error' is used",
	"error_dropped": "a failure has both 'reason_description' and a different 'error'; 'error' is dropped",
	"extra_value_overwritten": "the same key appears twice with different values (e.g. in the entry and its "
							   "'metadata'); only one is kept",
	"merged_entries": "several entries point at the same file and are merged into one",
	"merge_value_lost": "while merging entries for the same file, a different value for the same key is dropped",
	"value_not_carried_over": "a value in the old file appears nowhere in the converted file",
	"file_not_in_metadata": "a media file in the archive has no entry in the metadata",
	"metadata_file_missing": "the metadata lists a file that is not in the archive",
}

# Findings grouped by what they mean for converting the files on disk
FINDING_GROUPS = {
	"Lost: data that a converted file would no longer have": [
		"entry_not_a_record", "entry_without_file_dropped", "file_not_a_record", "file_without_filename_dropped",
		"blank_post_ids_dropped", "several_source_datasets", "error_dropped", "extra_value_overwritten",
		"merge_value_lost", "value_not_carried_over",
	],
	"Changed: read differently, nothing lost": [
		"unflagged_entry_as_failure", "ids_as_post_ids", "post_ids_as_text", "original_key_kept",
		"copied_entry_source_ignored", "single_post_id", "no_post_ids", "numeric_post_ids", "url_taken_from_key", "source_dataset_renamed",
		"failed_url_with_files", "retry_false_as_not_a_video", "failure_without_reason", "merged_entries",
	],
	"Archive does not match its metadata (with or without converting)": [
		"file_not_in_metadata", "metadata_file_missing",
	],
}

cli = argparse.ArgumentParser(description="Report what converting old-format .metadata.json files would drop or "
										  "change. Reads only; nothing is written to datasets.")
mode = cli.add_mutually_exclusive_group()
mode.add_argument("-k", "--key", help="Check one dataset, by key")
mode.add_argument("-f", "--file", nargs="+", help="Check these zip files directly, without the database")
cli.add_argument("-t", "--type", help="Only check datasets whose type starts with this, e.g. 'video-downloader'")
cli.add_argument("-n", "--examples", type=int, default=3, help="Examples to keep per finding per archive (default 3)")
cli.add_argument("-d", "--data-folder", help="Folder with the dataset files. Default: the data folder in "
											 "config/config.ini")
cli.add_argument("-o", "--out", help="Path and name for the report files, without extension. "
									 "Default: ./legacy-metadata-report-<timestamp>")
args = cli.parse_args()


def leaves(value, into):
	"""
	Collect the text and number values in a JSON structure, as text

	True/false and empty values are left out: they are mostly structure (e.g.
	'success') rather than data.

	:param value:  Decoded JSON
	:param set into:  Set to add the values to
	"""
	if isinstance(value, dict):
		for key, item in value.items():
			leaves(item, into)
	elif isinstance(value, list):
		for item in value:
			leaves(item, into)
	elif isinstance(value, bool) or value is None:
		return
	elif str(value).strip():
		into.add(str(value).strip())


class Findings:
	"""
	Counts findings for one archive and keeps a few examples of each
	"""
	def __init__(self, max_examples):
		self.counts = collections.Counter()
		self.examples = collections.defaultdict(list)
		self.max_examples = max_examples

	def add(self, finding, where="", detail=""):
		self.counts[finding] += 1
		if len(self.examples[finding]) < self.max_examples:
			self.examples[finding].append({"where": str(where)[:200], "detail": str(detail)[:500]})


def watch_extra(findings, outer_key, *sources):
	"""
	Note values that the conversion overwrites while gathering 'extra'

	Follows the same order as `MediaArchiveMetadata._legacy_extra`: per
	source, its own keys first, then those in its 'metadata' and 'extra'.
	"""
	skip = MediaArchiveMetadata._LEGACY_NON_EXTRA_KEYS
	seen = {}

	def set_value(key, value, origin):
		if key in seen and seen[key][0] != value:
			findings.add("extra_value_overwritten", outer_key,
						 f"'{key}': {seen[key][1]} value {json.dumps(seen[key][0], default=str)[:100]} replaced by "
						 f"{origin} value {json.dumps(value, default=str)[:100]}")
		seen[key] = (value, origin)

	for index, source in enumerate(sources):
		if not isinstance(source, dict):
			continue
		label = "entry" if index == 0 else "file"
		for key, value in source.items():
			if key not in skip:
				set_value(key, value, label)
		for nested_key in ("metadata", "extra"):
			nested = source.get(nested_key)
			if isinstance(nested, dict):
				for key, value in nested.items():
					set_value(key, value, f"{label} '{nested_key}'")


def check_post_ids(findings, outer_key, entry):
	"""
	Note how an entry's post IDs are read
	"""
	post_ids = entry.get("post_ids")
	if post_ids is None and "post_id" in entry:
		findings.add("single_post_id", outer_key, entry["post_id"])
		post_ids = [entry["post_id"]]
	if post_ids is None and "ids" in entry:
		findings.add("ids_as_post_ids", outer_key, entry["ids"])
		post_ids = entry["ids"]

	if post_ids is None:
		findings.add("no_post_ids", outer_key)
		return

	if isinstance(post_ids, str) and "," in post_ids:
		findings.add("post_ids_as_text", outer_key, post_ids)
		post_ids = post_ids.split(",")
	if isinstance(post_ids, (str, int)):
		post_ids = [post_ids]

	for post_id in post_ids if isinstance(post_ids, list) else []:
		if post_id is None or not str(post_id).strip():
			findings.add("blank_post_ids_dropped", outer_key, repr(post_id))
		elif isinstance(post_id, (int, float)) and not isinstance(post_id, bool):
			findings.add("numeric_post_ids", outer_key, post_id)


def check_legacy(raw, findings):
	"""
	Walk an old-format metadata file the way the conversion does, noting what
	it drops or changes

	This only observes; the conversion itself is done by `MediaArchiveMetadata`.

	:param dict raw:  Decoded old-format metadata
	:param Findings findings:  Where to note findings
	"""
	source_datasets = set()
	copied_sources = set()
	extra_per_file = {}

	def record_item(filename, outer_key, extra):
		if filename in extra_per_file:
			findings.add("merged_entries", outer_key, filename)
			existing = extra_per_file[filename]
			for key, value in extra.items():
				if key in existing and existing[key] != value:
					findings.add("merge_value_lost", outer_key,
								 f"{filename}: '{key}' kept {json.dumps(existing[key], default=str)[:100]}, dropped "
								 f"{json.dumps(value, default=str)[:100]}")
			extra_per_file[filename] = {**extra, **existing}
		else:
			extra_per_file[filename] = dict(extra)

	for outer_key, entry in raw.items():
		if not isinstance(entry, dict):
			findings.add("entry_not_a_record", outer_key, type(entry).__name__)
			continue

		check_post_ids(findings, outer_key, entry)

		if entry.get("url") is None and isinstance(outer_key, str) and outer_key.startswith(("http://", "https://")):
			findings.add("url_taken_from_key", outer_key)

		if entry.get("source_dataset") and not entry.get("from_dataset"):
			findings.add("source_dataset_renamed", outer_key, entry["source_dataset"])
		recorded_source = entry.get("from_dataset") or entry.get("source_dataset")
		if recorded_source and entry.get("file_dataset_key"):
			copied_sources.add(recorded_source)
		elif recorded_source:
			source_datasets.add(recorded_source)

		# what the reader keeps as `original_key`
		files = entry.get("files")
		post_ids = entry.get("post_ids", entry.get("ids", [entry.get("post_id")]))
		if isinstance(post_ids, str):
			post_ids = post_ids.split(",")
		known_values = {entry.get("url"), entry.get("filename")}
		known_values |= {str(post_id).strip() for post_id in post_ids or [] if post_id is not None}
		if isinstance(files, list):
			known_values |= {file.get("filename") for file in files if isinstance(file, dict)}
		if entry.get("url") is None and isinstance(outer_key, str) and outer_key.startswith(("http://", "https://")):
			known_values.add(outer_key)
		if outer_key not in known_values:
			findings.add("original_key_kept", outer_key)

		success = entry.get("success", True)
		files = entry.get("files")
		if isinstance(files, list) and files:
			files_recorded = False
			for file in files:
				if not isinstance(file, dict):
					findings.add("file_not_a_record", outer_key, type(file).__name__)
					continue
				if not file.get("success", True):
					if not file.get("reason"):
						findings.add("failure_without_reason", outer_key)
					if file.get("reason_description") and file.get("error") \
							and file["reason_description"] != file["error"]:
						findings.add("error_dropped", outer_key, file["error"])
					files_recorded = True
					continue
				filename = file.get("filename")
				if not filename or not isinstance(filename, str):
					findings.add("file_without_filename_dropped", outer_key, json.dumps(file, default=str)[:200])
					continue
				watch_extra(findings, outer_key, entry, file)
				record_item(filename, outer_key, MediaArchiveMetadata._legacy_extra(entry, file))
				files_recorded = True
			if files_recorded and not success:
				findings.add("failed_url_with_files", outer_key)
			if files_recorded or success:
				continue

		has_filename = entry.get("filename") and isinstance(entry["filename"], str)
		if success and has_filename:
			watch_extra(findings, outer_key, entry)
			record_item(entry["filename"], outer_key, MediaArchiveMetadata._legacy_extra(entry))
		elif not success or "success" not in entry:
			if "success" not in entry:
				findings.add("unflagged_entry_as_failure", outer_key, entry.get("error", ""))
			if entry.get("reason") is None and entry.get("retry") is False:
				findings.add("retry_false_as_not_a_video", outer_key)
			elif not entry.get("reason"):
				findings.add("failure_without_reason", outer_key)
			if entry.get("reason_description") and entry.get("error") \
					and entry["reason_description"] != entry["error"]:
				findings.add("error_dropped", outer_key, entry["error"])
		else:
			findings.add("entry_without_file_dropped", outer_key, json.dumps(entry, default=str)[:200])

	if len(source_datasets) > 1:
		findings.add("several_source_datasets", "", ", ".join(sorted(map(str, source_datasets))))
	for copied_source in sorted(map(str, copied_sources - source_datasets)):
		findings.add("copied_entry_source_ignored", "", copied_source)


def check_archive(path, max_examples):
	"""
	Check one archive

	:param Path path:  Path to the zip file
	:param int max_examples:  Examples to keep per finding
	:return dict:  What was found
	"""
	result = {"status": "", "note": "", "entries": "", "items_after": "", "failures_after": "",
			  "media_files": "", "findings": None}

	if not path.exists():
		result["status"] = "no_results_file"
		return result

	try:
		with zipfile.ZipFile(path, "r") as archive:
			names = [name for name in archive.namelist() if not name.endswith("/")]
			if METADATA_FILENAME not in names:
				result["status"] = "no_metadata_file"
				return result
			raw_bytes = archive.read(METADATA_FILENAME)
	except (zipfile.BadZipFile, OSError) as e:
		result["status"] = "unreadable_archive"
		result["note"] = str(e)
		return result

	media_files = {name for name in names if not is_support_file(name)}
	result["media_files"] = len(media_files)

	try:
		raw = json.loads(raw_bytes.decode("utf-8"))
	except (UnicodeDecodeError, json.JSONDecodeError) as e:
		result["status"] = "unreadable_metadata"
		result["note"] = str(e)
		return result

	if not isinstance(raw, dict):
		result["status"] = "not_an_object"
		return result

	if "schema_version" in raw:
		result["status"] = "already_current" if raw["schema_version"] == MediaArchiveMetadata.SCHEMA_VERSION \
			else "unknown_version"
		result["note"] = f"schema_version {raw['schema_version']}"
		return result

	result["status"] = "old_format"
	result["entries"] = len(raw)
	findings = Findings(max_examples)
	result["findings"] = findings

	# the real conversion, in memory only
	metadata = MediaArchiveMetadata()
	try:
		metadata._populate_from_raw(raw)
	except Exception as e:
		result["status"] = "conversion_failed"
		result["note"] = f"{type(e).__name__}: {e}"
		return result

	result["items_after"] = len(metadata.items)
	result["failures_after"] = len(metadata.failures)

	try:
		check_legacy(raw, findings)
	except Exception as e:
		# a gap in this script, not in the conversion
		result["note"] = f"could not finish checking: {type(e).__name__}: {e}"

	# anything in the old file that is nowhere in the new one, whatever the cause
	old_values = set(map(str, raw.keys()))
	leaves(raw, old_values)
	new_values = set(metadata.items.keys())
	leaves(metadata.to_dict(), new_values)
	for value in sorted(old_values - new_values):
		findings.add("value_not_carried_over", "", value)

	# compare the metadata with the files actually in the archive
	for filename in sorted(media_files - set(metadata.items)):
		findings.add("file_not_in_metadata", filename)
	for filename in sorted(set(metadata.items) - media_files):
		findings.add("metadata_file_missing", filename)

	return result


def get_datasets():
	"""
	Get the datasets to check from the database (read only)

	:return tuple:  A list of (dataset info, path) tuples, and a note on what was selected
	"""
	from common.config_manager import ConfigManager
	from common.lib.database import Database
	from common.lib.logger import Logger

	config = ConfigManager()
	log_path = config.get("PATH_ROOT").joinpath(config.get("PATH_LOGS")).joinpath("check-legacy-metadata.log")
	logger = Logger(log_path=log_path, output=False)
	database = Database(logger=logger, dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD,
						host=config.DB_HOST, port=config.DB_PORT, appname="check-legacy-metadata")
	data_folder = Path(args.data_folder) if args.data_folder else Path(config.get("PATH_DATA"))
	print(f"Database:    {config.DB_NAME} on {config.DB_HOST}:{config.DB_PORT} (as {config.DB_USER})")
	print(f"Data folder: {data_folder}")
	if not data_folder.is_dir():
		print("The data folder does not exist; use --data-folder to say where the dataset files are.")
		sys.exit(1)

	columns = "key, type, timestamp, result_file, is_finished, software_version, num_rows"
	if args.key:
		rows = database.fetchall(f"SELECT {columns} FROM datasets WHERE key = %s", (args.key,))
	else:
		rows = database.fetchall(f"SELECT {columns} FROM datasets WHERE result_file LIKE %s ORDER BY timestamp",
								 ("%.zip",))

	if args.type:
		rows = [row for row in rows if (row["type"] or "").startswith(args.type)]

	return [(row, Path(data_folder).joinpath(row["result_file"])) for row in rows]


if args.file:
	datasets = [({"key": "", "type": "", "timestamp": None, "result_file": file, "is_finished": "",
				  "software_version": "", "num_rows": ""}, Path(file)) for file in args.file]
else:
	datasets = get_datasets()

out = Path(args.out) if args.out else Path.cwd().joinpath(f"legacy-metadata-report-{int(time.time())}")
print(f"Checking {len(datasets):,} archive(s)...")

rows = []
details = {}
by_status = collections.Counter()
by_type = collections.defaultdict(collections.Counter)
by_year = collections.defaultdict(collections.Counter)
finding_archives = collections.Counter()
finding_types = collections.defaultdict(set)
finding_total = collections.Counter()

for index, (dataset, path) in enumerate(datasets):
	if index and index % 250 == 0:
		print(f"  ...{index:,} of {len(datasets):,}")

	result = check_archive(path, args.examples)
	created = datetime.datetime.fromtimestamp(dataset["timestamp"]).strftime("%Y-%m-%d") \
		if dataset["timestamp"] else ""
	year = created[:4] or "unknown"
	dataset_type = dataset["type"] or "unknown"
	findings = result["findings"]

	by_status[result["status"]] += 1
	by_type[dataset_type][result["status"]] += 1
	by_year[year][result["status"]] += 1

	if findings:
		for finding, count in findings.counts.items():
			finding_archives[finding] += 1
			finding_total[finding] += count
			finding_types[finding].add(dataset_type)

	rows.append({
		"key": dataset["key"],
		"type": dataset_type,
		"created": created,
		"finished": dataset["is_finished"],
		"software_version": dataset["software_version"],
		"num_rows": dataset["num_rows"],
		"result_file": dataset["result_file"],
		"status": result["status"],
		"entries": result["entries"],
		"items_after": result["items_after"],
		"failures_after": result["failures_after"],
		"media_files": result["media_files"],
		"findings": "; ".join(f"{finding}={count}" for finding, count in sorted(findings.counts.items()))
		if findings else "",
		"note": result["note"],
	})

	if findings and (findings.counts or result["note"]):
		details[dataset["key"] or dataset["result_file"]] = {
			"type": dataset_type,
			"created": created,
			"software_version": dataset["software_version"],
			"status": result["status"],
			"note": result["note"],
			"findings": {finding: {"count": findings.counts[finding], "examples": findings.examples[finding]}
						 for finding in sorted(findings.counts)},
		}

csv_path = out.with_suffix(".csv")
with csv_path.open("w", encoding="utf-8", newline="") as outfile:
	writer = csv.DictWriter(outfile, fieldnames=list(rows[0].keys()) if rows else ["key"])
	writer.writeheader()
	writer.writerows(rows)

details_path = out.parent.joinpath(out.name + "-details.json")
with details_path.open("w", encoding="utf-8") as outfile:
	json.dump({"what_findings_mean": FINDINGS, "archives": details}, outfile, indent=2, default=str)


def print_table(title, counter_per_group):
	statuses = sorted(by_status)
	print(f"\n{title}")
	print("  " + "group".ljust(36) + "".join(status[:18].rjust(20) for status in statuses))
	for group in sorted(counter_per_group):
		counts = counter_per_group[group]
		print("  " + str(group)[:36].ljust(36) + "".join(str(counts.get(status, "")).rjust(20) for status in statuses))


print("\nArchives by status:")
for status, count in by_status.most_common():
	print(f"  {status}: {count:,}")

print_table("By processor type:", by_type)
print_table("By year the dataset was made:", by_year)

print("\nFindings in old-format archives (archives / times / processor types):")
if not finding_archives:
	print("  none")
for group, group_findings in FINDING_GROUPS.items():
	found = [finding for finding in group_findings if finding in finding_archives]
	if not found:
		continue
	print(f"\n  {group}")
	for finding in sorted(found, key=lambda finding: -finding_archives[finding]):
		print(f"    {finding}: {finding_archives[finding]:,} archive(s), {finding_total[finding]:,} time(s), "
			  f"in {', '.join(sorted(finding_types[finding]))}")
		print(f"        {FINDINGS[finding]}")

print(f"\nPer archive: {csv_path}")
print(f"Examples:    {details_path}")
