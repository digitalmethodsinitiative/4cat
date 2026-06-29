"""
Inspect unmappable items in a dataset.

Re-runs the datasource's `map_item` over its source NDJSON and reports every
item that raises an exception. Failures are grouped by signature (error type,
file:line inside map_item) so repeated formats collapse into one entry.

A JSON report is written into PATH_DATA, named with the dataset key so the
clean_results.py maintenance script associates it with the dataset (and
cleans it up if the dataset is later deleted).
"""
import argparse
import inspect as py_inspect
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")

from common.config_manager import ConfigManager
from common.lib.database import Database
from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException, MapItemException
from common.lib.logger import Logger
from common.lib.module_loader import ModuleCollector


cli = argparse.ArgumentParser(
	description="Re-run map_item over a dataset's NDJSON and report unmappable items, grouped by file:line signature."
)
mode = cli.add_mutually_exclusive_group(required=True)
mode.add_argument("-k", "--key", help="Dataset key. Resolves NDJSON path and datasource via the database.")
mode.add_argument("-f", "--file", help="Path to an NDJSON file. Requires --datasource.")
cli.add_argument("-d", "--datasource", help="Datasource type (e.g. 'twitter-import'). Required with --file.")
cli.add_argument("-n", "--samples", type=int, default=3,
				 help="Full sample items to keep per failure signature (default 3). 0 = indices only.")
cli.add_argument("--success-samples", type=int, default=5,
				 help="Max successful items to keep as reference, one per distinct top-level key signature (default 5).")
cli.add_argument("-o", "--out", help="Override output path. Default: PATH_DATA/unmappable-<ts>-<key>.json.")
args = cli.parse_args()

if args.file and not args.datasource:
	cli.error("--file requires --datasource")

config = ConfigManager()
log_folder = config.get('PATH_ROOT').joinpath(config.get('PATH_LOGS')).joinpath("inspect-unmappable.log")
logger = Logger(log_path=log_folder, output=True, log_level="DEBUG")
database = Database(logger=logger, 
				  	dbname=config.DB_NAME, 
					user=config.DB_USER, 
					password=config.DB_PASSWORD, 
					host=config.DB_HOST, 
					port=config.DB_PORT,
					appname="inspect-unmappable")
config.with_db(database)

modules = ModuleCollector(config=config)

# Resolve dataset / processor / NDJSON path
dataset_key = None
if args.key:
	try:
		dataset = DataSet(key=args.key, db=database, modules=modules)
	except DataSetException:
		print(f"No dataset with key {args.key}")
		sys.exit(1)
	processor = dataset.get_own_processor()
	if processor is None:
		print(f"Dataset type '{dataset.data['type']}' has no known processor in this 4CAT install.")
		sys.exit(1)
	ndjson_path = dataset.get_results_path()
	dataset_key = dataset.key
	datasource_id = dataset.data["type"]
else:
	ndjson_path = Path(args.file)
	if not ndjson_path.exists():
		print(f"File not found: {ndjson_path}")
		sys.exit(1)
	processor = modules.processors.get(args.datasource)
	if processor is None:
		print(f"Unknown datasource: {args.datasource}")
		known = sorted(k for k, v in modules.processors.items() if hasattr(v, "map_item"))
		print(f"Datasources with map_item: {', '.join(known)}")
		sys.exit(1)
	datasource_id = args.datasource

if ndjson_path.suffix.lower() != ".ndjson":
	print(f"Only NDJSON datasets are supported (got {ndjson_path.suffix}).")
	sys.exit(1)

if not ndjson_path.exists():
	print(f"Source file does not exist: {ndjson_path}")
	sys.exit(1)

if not hasattr(processor, "map_item"):
	print(f"Processor {processor.type} has no map_item method.")
	sys.exit(1)

try:
	processor_file = Path(py_inspect.getfile(processor)).resolve()
except TypeError:
	processor_file = None


def pick_frame(exc):
	"""Pick the innermost traceback frame inside the processor's own file."""
	frames = traceback.extract_tb(exc.__traceback__)
	if not frames:
		return None
	if processor_file is not None:
		for frame in reversed(frames):
			try:
				if Path(frame.filename).resolve() == processor_file:
					return frame
			except OSError:
				continue
	return frames[-1]


print(f"Inspecting {ndjson_path}")
print(f"  datasource: {datasource_id}")
if dataset_key:
	print(f"  dataset:    {dataset_key}")

signatures = {}
successful_buckets = {}  # tuple(sorted(top-level keys)) -> {"index": int, "item": dict}
total = 0
unmappable = 0
start = time.time()

with ndjson_path.open(encoding="utf-8") as infile:
	for i, line in enumerate(infile):
		total += 1

		try:
			item = json.loads(line)
		except json.JSONDecodeError as e:
			unmappable += 1
			sig_key = ("JSONDecodeError", str(e), ndjson_path.name, 0)
			sig = signatures.setdefault(sig_key, {
				"error_type": "JSONDecodeError",
				"error_value": str(e),
				"filename": ndjson_path.name,
				"lineno": 0,
				"code_context": "",
				"count": 0,
				"sample_indices": [],
				"samples": [],
				"source_urls": set(),
				"item_ids": set(),
			})
			sig["count"] += 1
			sig["sample_indices"].append(i)
			if len(sig["samples"]) < args.samples:
				sig["samples"].append({"index": i, "raw_line": line[:1000]})
			continue

		try:
			mapped = processor.map_item(item)
			if not mapped:
				# matches the falsy check in processor.py:893
				raise MapItemException("map_item returned a falsy value")
			# Successful map — keep one reference per distinct top-level key signature,
			# up to the overall cap. Top-level keys catch the common "two shapes" case
			# (e.g. modern vs. legacy Twitter); deeper drift is left to manual diffing.
			if len(successful_buckets) < args.success_samples and isinstance(item, dict):
				shape = tuple(sorted(item.keys()))
				if shape not in successful_buckets:
					successful_buckets[shape] = {"index": i, "item": item}
			continue
		except KeyboardInterrupt:
			raise
		except MapItemException as e:
			# Intentional reject by the datasource (e.g. Instagram ads)
			frame = pick_frame(e)
			error_type = "MapItemException"
			error_value = str(e)
		except Exception as e:
			frame = pick_frame(e)
			error_type = type(e).__name__
			# For KeyError, str(e) is the repr of the missing key — preserve it verbatim
			error_value = repr(e.args[0]) if isinstance(e, KeyError) and e.args else str(e)

		unmappable += 1
		fname = Path(frame.filename).name if frame else "?"
		lineno = frame.lineno if frame else 0
		code = frame.line if frame else ""
		sig_key = (error_type, error_value, fname, lineno)
		sig = signatures.setdefault(sig_key, {
			"error_type": error_type,
			"error_value": error_value,
			"filename": fname,
			"lineno": lineno,
			"code_context": code,
			"count": 0,
			"sample_indices": [],
			"samples": [],
			"source_urls": set(),
			"item_ids": set(),
		})
		sig["count"] += 1
		sig["sample_indices"].append(i)
		if len(sig["samples"]) < args.samples:
			sig["samples"].append({"index": i, "item": item})

		# Roll up Zeeschuimer capture context — useful for filing an issue
		# upstream when the failure pattern points at collection rather than
		# the mapper.
		if isinstance(item, dict):
			src_url = item.get("__import_meta", {}).get("source_platform_url", "")
			if src_url:
				sig["source_urls"].add(src_url)
			for id_key in ("rest_id", "id", "pk", "shortcode"):
				id_val = item.get(id_key)
				if id_val:
					sig["item_ids"].add(str(id_val))
					break

elapsed = time.time() - start

# Determine output path
if args.out:
	out_path = Path(args.out)
elif dataset_key:
	# unmappable-<ts>-<key>.json — clean_results.py will associate this with the dataset
	out_path = Path(config.get("PATH_DATA")).joinpath(f"unmappable-{int(time.time())}-{dataset_key}.json")
else:
	# No dataset; drop the report next to the source file
	out_path = ndjson_path.with_name(f"unmappable-{int(time.time())}-{ndjson_path.stem}.json")

# Sort signatures: most frequent first
sorted_sigs = sorted(signatures.values(), key=lambda s: s["count"], reverse=True)

# Normalise the rollup sets to sorted lists for JSON serialisation,
# and aggregate across signatures for the Zeeschuimer upstream report.
all_source_urls = set()
all_item_ids = set()
for sig in sorted_sigs:
	all_source_urls |= sig["source_urls"]
	all_item_ids |= sig["item_ids"]
	sig["source_urls"] = sorted(sig["source_urls"])
	sig["item_ids"] = sorted(sig["item_ids"])

zeeschuimer_report = {
	"source_urls_unique": sorted(all_source_urls),
	"item_ids_unique": sorted(all_item_ids),
	"per_signature": [
		{
			"label": f"{s['error_type']} {s['error_value']} at {s['filename']}:{s['lineno']}",
			"count": s["count"],
			"source_urls": s["source_urls"],
			"item_ids": s["item_ids"],
		}
		for s in sorted_sigs
	],
}

successful_samples = [
	{"index": v["index"], "top_level_keys": list(k), "item": v["item"]}
	for k, v in successful_buckets.items()
]

report = {
	"dataset_key": dataset_key,
	"datasource": datasource_id,
	"source_file": str(ndjson_path),
	"generated_at": int(time.time()),
	"total_items": total,
	"unmappable_items": unmappable,
	"signatures": sorted_sigs,
	"successful_samples": successful_samples,
	"zeeschuimer_report": zeeschuimer_report,
}

out_path.parent.mkdir(parents=True, exist_ok=True)
with out_path.open("w", encoding="utf-8") as outfile:
	json.dump(report, outfile, indent=2, default=str)

print()
print(f"Scanned {total} items in {elapsed:.1f}s; {unmappable} unmappable ({len(signatures)} signatures); "
	  f"{len(successful_samples)} reference sample(s) saved.")
if sorted_sigs:
	print()
	for n, sig in enumerate(sorted_sigs, 1):
		loc = f"{sig['filename']}:{sig['lineno']}" if sig["lineno"] else sig["filename"]
		head = f"  [{n}] {sig['error_type']} {sig['error_value']} at {loc} — {sig['count']} item(s)"
		print(head)
		if sig["code_context"]:
			print(f"      code:    {sig['code_context'].strip()}")
		sample_preview = ", ".join(str(s) for s in sig["sample_indices"][:5])
		more = "" if len(sig["sample_indices"]) <= 5 else f", … (+{len(sig['sample_indices']) - 5})"
		print(f"      indices: {sample_preview}{more}")
		if sig["source_urls"]:
			print(f"      source URLs ({len(sig['source_urls'])} unique): {sig['source_urls'][0]}"
				  + ("" if len(sig["source_urls"]) == 1 else f" (+{len(sig['source_urls']) - 1})"))
if all_source_urls:
	print()
	print(f"Unique Zeeschuimer source URLs across all failures: {len(all_source_urls)} "
		  f"(see report['zeeschuimer_report'] for the full pasteable list).")
print()
print(f"Report: {out_path}")
