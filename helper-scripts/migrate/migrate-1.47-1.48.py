<<<<<<< HEAD
# Update the 'annotations' table so every annotation has its own row.
# also add extra data
import sys
import os
import json
=======
# Add timestamp_finished column to datasets table
import json
import sys
import os
import datetime
>>>>>>> master

from pathlib import Path

sys.path.insert(0, os.path.join(os.path.abspath(os.path.dirname(__file__)), "../.."))
from common.lib.database import Database
from common.lib.logger import Logger
<<<<<<< HEAD
=======
from common.lib.dataset import DataSet
from common.lib.helpers import get_last_line
>>>>>>> master

log = Logger(output=True)

import configparser

ini = configparser.ConfigParser()
ini.read(Path(__file__).parent.parent.parent.resolve().joinpath("config/config.ini"))
db_config = ini["DATABASE"]

db = Database(logger=log, dbname=db_config["db_name"], user=db_config["db_user"], password=db_config["db_password"],
              host=db_config["db_host"], port=db_config["db_port"], appname="4cat-migrate")

<<<<<<< HEAD

datasets = db.fetchall("SELECT * FROM datasets WHERE annotation_fields != ''")

print("  Converting annotation options from lists to dicts...")
for dataset in datasets:

    annotation_fields = dataset["annotation_fields"]

    # Flatten options from list of dicts to dict
    options_converted = False
    annotation_fields = json.loads(annotation_fields)
    new_annotation_fields = annotation_fields

    for field_id, annotation_field in annotation_fields.items():

        if "options" in annotation_field:
            flattened_options = {}

            if isinstance(annotation_field["options"], list):
                for op in annotation_field["options"]:
                    flattened_options.update(op)
                new_annotation_fields[field_id]["options"] = flattened_options
                options_converted = True

    if options_converted:
        print("    Converting annotation options to list for dataset %s..." % dataset["key"])
        db.execute("UPDATE datasets SET annotation_fields = %s WHERE key = %s;", (json.dumps(new_annotation_fields), dataset["key"]))

print("  Expanding the 'annotations' table.")

print("    Creating new annotations table...")
db.execute("""
CREATE TABLE IF NOT EXISTS annotations_new (
  id                SERIAL PRIMARY KEY,
  dataset           TEXT,
  field_id          TEXT,
  item_id           TEXT,
  timestamp         INT DEFAULT 0,
  timestamp_created INT DEFAULT 0,
  label             TEXT,
  type              TEXT,
  options           TEXT,
  value             TEXT,
  author            TEXT,
  author_original   TEXT,
  by_processor      BOOLEAN DEFAULT FALSE,
  metadata          TEXT
);
""")

print("    Creating indexes for annotations table...")
db.execute("""
CREATE UNIQUE INDEX IF NOT EXISTS annotation_id
  ON annotations_new (
    id
);
CREATE UNIQUE INDEX IF NOT EXISTS annotation_unique
  ON annotations_new (
    label,
    dataset,
    item_id
);
CREATE INDEX IF NOT EXISTS annotation_value
  ON annotations_new (
    value
);
CREATE INDEX IF NOT EXISTS annotation_timestamp
  ON annotations_new (
    timestamp
);
""")

print("    Transferring old annotations to new annotations table...")

annotations = db.fetchall("SELECT * FROM annotations;")

if not annotations:
    print("    No annotation fields to transfer, skipping...")

elif  "key" not in annotations[0] and "dataset" in annotations[0]:
    print("    Annotations table seems to have been updated already")

else:
    
    count = 0
    skipped_count = 0

    columns = "id,dataset,field_id,item_id,timestamp,timestamp_created,label,type,options,value,author,author_original,by_processor,metadata"

    # Each row are **all** annotations per dataset
    for row in annotations:

        dataset = db.fetchone("SELECT * FROM datasets WHERE key = '" + row["key"] + "';")
        # If the dataset is not present anymore,
        # we're going to skip these annotations;
        # likely the dataset is expired.
        if not dataset:
            print("      No dataset found for key %s, skipping..." % row["key"])
            skipped_count += 1
            continue

        annotation_fields = dataset["annotation_fields"]
        if annotation_fields:
            annotation_fields = json.loads(dataset.get("annotation_fields"))
        else: annotation_fields = {}

        author = dataset.get("creator", "")

        if not row.get("annotations"):
            print("      No annotations for dataset %s, skipping..." % row["key"])
            skipped_count += 1
            continue

        # Loop through all annotated posts
        for post_id, post_annotations in json.loads(row["annotations"]).items():

            # Loop through individual annotations per post
            for label, value in post_annotations.items():

                # Get the ID of this particular annotation field
                field_id = [k for k, v in annotation_fields.items() if v["label"] == label]

                if field_id:
                    field_id = field_id[0]
                    
                # Skip if this field was not saved to the datasets table
                if not field_id or field_id not in annotation_fields:
                    print("      Annotation field ID not saved to datasets table, skipping...")
                    skipped_count += 1
                    continue

                ann_type = annotation_fields[field_id]["type"]
                options = annotation_fields[field_id]["options"] if "options" in annotation_fields[field_id] else ""
                options = {k: v for d in options for k, v in d.items()} # flatten

                if isinstance(value, list):
                    value = ",".join(value)

                inserts = [(
                    row["dataset"],         # dataset
                    int(field_id),          # field_id; this is an ID for the same type of input field.
                    str(post_id),           # post_id; needs to be a string, changes per data source.
                    dataset["timestamp"],   # timestamp
                    dataset["timestamp"],   # timestamp_created
                    label,                  # label
                    ann_type,               # type
                    json.dumps(options) if options else "",    # options; each option has a key and a value.
                    value,                  # value
                    author,                 # author
                    author,                 # author_original
                    False,                  # by_processor
                    json.dumps({}),         # metadata
                )]

                db.execute("INSERT INTO annotations_new (" + columns + ") VALUES %s", replacements=inserts)

                count += 1

        if count % 10 == 0:
            print("      Transferred %s annotations..." % count)
        
    print("    Done, transferred %s annotations and skipped %s annotations" % (count, skipped_count))

print("  Deleting old annotations table...")
db.execute("DROP TABLE annotations")

print("  Renaming new annotations table...")
db.execute("ALTER TABLE annotations_new RENAME TO annotations;")

print("  - done!")
=======
print("  Checking if datasets table has a column 'timestamp_finished'...")
has_column = db.fetchone(
    "SELECT COUNT(*) AS num FROM information_schema.columns WHERE table_name = 'datasets' AND column_name = 'timestamp_finished'")
if has_column["num"] == 0:
    print("  ...No, adding.")
    db.execute("ALTER TABLE datasets ADD COLUMN timestamp_finished INTEGER DEFAULT NULL")
    print("  ...Added column. Updating datasets with information based on logs.")
    dataset_ids = db.fetchall("SELECT key FROM datasets WHERE is_finished = TRUE")
    unable_to_update = []
    update_data = []

    for dataset in dataset_ids:
        key = dataset["key"]
        dataset = DataSet(key=key, db=db)

        if dataset.get_log_path().exists():
            try:
                timestamp_finished = datetime.datetime.strptime(get_last_line(dataset.get_log_path())[:24], "%c")
                update_data.append((key, int(timestamp_finished.timestamp())))
            except ValueError as e:
                # Unable to parse datetime from last line
                print(f" ...Unable to parse datetime from last line for dataset {key}: {e}")
                unable_to_update.append(key)
        else:
            # No log file; unable to determine timestamp_finished
            print(f" ...Unable to determine timestamp_finished for dataset {key}; no log file.")
            unable_to_update.append(key)

    if update_data:
        db.execute_many("UPDATE datasets SET timestamp_finished = data.timestamp_finished FROM (VALUES %s) AS data (key, timestamp_finished) WHERE datasets.key = data.key", replacements=update_data)

    db.commit()
    print(f"  ...Updated {len(update_data)} datasets.")
    if len(unable_to_update) > 0:
        print("  ...Unable to update the following datasets:")
        for key in unable_to_update:
            print(f"    {key}")
    else:
        print("  ...All datasets updated.")

else:
    print("  ...Yes, nothing to update.")
>>>>>>> master
