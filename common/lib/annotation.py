"""
Annotation class
"""


import time
import json

from common.lib.helpers import hash_values
from common.lib.exceptions import AnnotationException


class Annotation:
    """
    Annotation class

    Annotations are always tied to a dataset, a dataset item (e.g. a csv row),
    an annotation label, and a type ('text', 'multichoice', etc.).

    """

    # Attributes must be created here to ensure getattr and setattr work properly

    data = None
    db = None

    id = None                 # Unique ID for this annotation
    item_id = None            # ID of the item for this annotation, e.g. post ID
    field_id = None           # If of this type of annotation field for this dataset
    dataset = None            # Dataset key this annotation is generated from
    timestamp = None          # When this annotation was edited
    timestamp_created = None  # When this timestamp was created
    label = None              # Label of annotation
    type = None               # Type of annotation (e.g. `text`)
    options = None            # Possible options
    value = None              # The actual annotation value
    author = None             # Who last edited the annotation
    author_original = None    # Who originally made the annotation
    by_processor = None       # Whether the annotation was made by a processor
    metadata = None           # Misc metadata

    def __init__(self, data=None, id=None, db=None):
        """
        Instantiate annotation object.

        :param data:    Annotation data; should correspond to the annotations table record.
        :param id:      The ID of an annotation. If given, it retrieves the annotation
                        from the database.
        :param db:      Database connection object
        """

        required_fields = ["label", "item_id", "dataset"]

        # Must have an ID or data
        if (id is None and data is None) or (data is not None and not isinstance(data, dict)):
            raise AnnotationException("Annotation() requires either a valid `data` dictionary or ID.")

        if not db:
            raise AnnotationException("Annotation() needs a `db` database object")

        self.db = db

        current = None
        new_or_updated = False

        # Get the annotation data if the ID is given; if an annotation has
        # an ID, it is guaranteed to be in the database.
        # IDs can both be explicitly given or present in the data dict.
        if id is not None or "id" in data:
            if data and "id" in data:
                id = data["id"]
            self.id = id # IDs correspond to unique serial numbers in the database.
            current = self.get_by_id(id)
            if not current:
                raise AnnotationException(
                    "Annotation() requires a valid ID for an existing annotation, %s given" % id)

        # If an ID is not given, get or create an Annotation object from its data.
        # First check if required fields are present in `data`.
        else:
            for required_field in required_fields:
                if required_field not in data or not data[required_field]:
                    raise AnnotationException("Annotation() requires a %s field" % required_field)

            # Check if this annotation already exists, based on dataset key, item id, and label.
            current = self.get_by_field(data["dataset"], data["item_id"], data["label"])

        # If we were able to retrieve an annotation from the db, it already exists
        if current:
            # Check if we have to overwrite old data with new data
            if data:
                for key, value in data.items():
                    # Save unknown fields in metadata
                    if key not in current:
                        current["metadata"][key] = value
                        new_or_updated = True
                    # If values differ, update the value
                    elif current[key] != value:
                        current[key] = value
                        new_or_updated = True

            self.data = current

        # If this is a new annotation, set all the properties.
        else:
            # Keep track of when the annotation was made
            created_timestamp = int(time.time())

            new_data = {
                "dataset": data["dataset"],
                "item_id": data["item_id"],
                "field_id": data["field_id"] if data.get("field_id") else self.set_field_id(data["dataset"], data["label"]),
                "timestamp": created_timestamp,
                "timestamp_created": created_timestamp,
                "label": data["label"],
                "type": data.get("type", "text"),
                "options": data.get("options", ""),
                "value": data.get("value", ""),
                "author": data.get("author", ""),
                "author_original": data.get("author", ""),
                "by_processor": data.get("by_processor", False),
                "metadata": data.get("metadata", {}),
            }

            self.data = new_data
            new_or_updated = True

        if isinstance(self.data["metadata"], str):
            try:
                self.metadata = json.loads(self.data["metadata"])
            except (TypeError, json.JSONDecodeError):
                self.metadata = {}

        for k, v in self.data.items():
            # Some type checking
            try:
                if k == "timestamp" or k == "timestamp_created":
                    v = int(v)
                elif k == "by_processor":
                    v = bool(v)
            except ValueError as e:
                raise AnnotationException("Annotation fields are not of the right type (%s)" % e)
            self.__setattr__(k, v)

        # Write to db if anything changed
        if new_or_updated:
            self.timestamp = int(time.time())
            self.write_to_db()

    def get_by_id(self, id: int):
        """
        Get annotation by ID

        :param str id:  ID of annotation
        :param db:      Database connection object
        :return:  Annotation object, or an empty dict if the ID doesn't exist.
        """

        try:
            int(id)
        except ValueError:
            raise AnnotationException("Id '%s' is not valid" % id)

        data = self.db.fetchone("SELECT * FROM annotations WHERE id = %s" % (id))

        if not data:
            return {}

        if data["type"] == "checkbox":
            data["value"] = data["value"].split(",")
        data["metadata"] = json.loads(data["metadata"])

        return data

    def get_by_field(self, dataset_key: str, item_id: str, label: str) -> dict:
        """
        Get the annotation information via its dataset key, item ID, and field_id.
        This is always a unique combination.

        :param dataset_key:     The key of the dataset this annotation was made for.
        :param item_id:         The ID of the item this annotation was made for.
        :param label:           The label of the annotation.

        :return data: A dict with data of the retrieved annotation, or an empty dict if it doesn't exist.
        """

        data = self.db.fetchone("SELECT * FROM annotations WHERE dataset = %s AND item_id = %s AND label = %s",
                         (dataset_key, str(item_id), label))
        if not data:
            return {}

        if data["type"] == "checkbox":
            data["value"] = data["value"].split(",")
        data["metadata"] = json.loads(data["metadata"])

        return data

    def set_field_id(self, dataset_key: str, label: str) -> str:
        """
        Sets a `field_id` based on the dataset key and label.
        This combination should be unique.

        :param dataset_key: The dataset key
        :param label:       The label of the dataset.
        """

        base_field_id = dataset_key + label
        field_id = hash_values(base_field_id)
        self.field_id = field_id
        return self.field_id

    def write_to_db(self):
        """
        Write an annotation to the database.
        """
        db_data = self.data

        db_data["timestamp"] = int(time.time())
        m = db_data["metadata"] # To avoid circular reference error
        db_data["metadata"] = json.dumps(m)
        if db_data["type"] == "checkbox":
            db_data["value"] = ",".join(db_data["value"])

        return self.db.upsert("annotations", data=db_data, constraints=["label", "dataset", "item_id"])

    def delete(self):
        """
        Deletes this annotation
        """
        return self.db.delete("annotations", {"id": self.id})

    @staticmethod
    def delete_many(db, dataset_key=None, id=None, field_id=None):
        """
        Deletes annotations for an entire dataset or by a list of (field) IDs.

        :param db:              Database object.
        :param str dataset_key: A dataset key.
        :param li id:			A list or string of unique annotation IDs.
        :param li field_id:		A list or string of IDs for annotation fields.

        :return int: The number of removed records.
        """
        if not dataset_key and not id and not field_id:
            return 0

        where = {}
        if dataset_key:
            where["dataset"] = dataset_key
        if id:
            where["id"] = id
        if field_id:
            where["field_id"] = field_id

        return db.delete("annotations", where)

    @staticmethod
    def update_annotations_via_fields(dataset_key, old_fields: dict, new_fields: dict, db) -> int:
        """
        Updates annotations in the annotations table if the input fields
        themselves have been changed, for instance if a dropdown label is renamed
        or a field is deleted.

        :param str  dataset_key:    The dataset key for which fields changed.
        :param dict old_fields:	    Old annotation fields.
        :param dict new_fields:	    New annotation fields; this should contain not just
                                    the additions, but all fields, changed or otherwise.
        :param db:                  Database object so we can write.

        :returns int:               How many records were affected.
        """

        text_fields = ["textarea", "text"]

        # If old and new fields are identical, do nothing.
        if old_fields == new_fields:
            return 0

        fields_to_delete = set()        # Delete all annotations with this field ID
        fields_to_update = {}           # Update values of annotations with this field ID
        old_options = {}

        # Loop through the old annotation fields
        for old_field_id, old_field in old_fields.items():

            # Delete all annotations of this type if the field is deleted.
            if old_field_id not in new_fields:
                fields_to_delete.add(old_field_id)
                continue

            field_id = old_field_id
            new_field = new_fields[field_id]

            # If the annotation type has changed, also delete existing annotations,
            # except between text and textarea, where we can just change the type and keep the text.
            if old_field["type"] != new_field["type"]:
                if not old_field["type"] in text_fields and not new_field["type"] in text_fields:
                    fields_to_delete.add(field_id)
                    continue

            # Loop through all the key/values in the new field settings
            # and update in case it's different from the old values.
            update_data = {}
            for field_key, field_value in new_field.items():

                # Update if values don't match
                if field_value != old_field.get(field_key):

                    # Special case: option values that are removed/renamed.
                    # Here we may have to change/delete values within the
                    # values column.
                    if field_key == "options":

                        new_options = field_value

                        # Edge case: delete annotations of this type if all option fields are deleted
                        if not new_options:
                            fields_to_delete.add(field_id)
                            continue

                        # Changed options values (e.g. renamed or one field deleted)
                        old_options[old_field_id] = old_field.get("options", {})
                        options_to_update = {}
                        if old_options[old_field_id] and old_options != new_options:
                            options_to_update = new_options

                        # # Options are saved in a dict with IDs as keys and labels as values.
                        # for old_option_id, old_option in old_options.items():
                        #
                        #     # Renamed option label
                        #     if old_option_id in new_options and old_option != new_options[old_option_id]:
                        #         options_to_update[old_option] = new_options[old_option_id]  # Old label -> new label
                        #     # Deleted option
                        #     elif old_option_id not in new_options:
                        #         options_to_update[old_option] = None  # Remove None labels later

                        if options_to_update:
                            update_data[field_key] = {"options": options_to_update}

                    # For all other changes, just overwrite with new data.
                    else:
                        update_data[field_key] = field_value

            if update_data:
                fields_to_update[field_id] = update_data

        # Delete annotations
        if fields_to_delete:
            Annotation.delete_many(db, field_id=list(fields_to_delete))

        # Write changes to fields to database
        count = 0
        if fields_to_update:
            for field_id, updates in fields_to_update.items():

                # Write to db
                for column, update_value in updates.items():

                    update_value_insert = update_value
                    if column == "options":
                        update_value_insert = ",".join(list(update_value["options"].values()))

                    # Change values of columns
                    updates = db.update("annotations", {column: update_value_insert},
                                        where={"dataset": dataset_key, "field_id": field_id})
                    count += updates

                    # Special case: Changed option labels.
                    # Here we have to also rename/remove inserted options from the `value` column.
                    if column == "options":

                        annotations = db.fetchall("SELECT id, options, value FROM annotations "
                                                      "WHERE dataset = '%s' and field_id = '%s' AND value != '';"
                                                       % (dataset_key, field_id))

                        for annotation in annotations:
                            annotation_id = annotation["id"]
                            annotation_values = annotation["value"].split(",")

                            # Remove or rename options
                            new_values = []
                            new_options = update_value["options"] # Dict with option id->label as items

                            for ann_value in annotation_values:
                                # Get the option ID, so we can see if it's new, deleted, or renamed.
                                # Should always be present in old options dict
                                option_id = [k for k, v in old_options[field_id].items() if v == ann_value][0]
                                # Deleted...
                                if option_id not in new_options:
                                    continue
                                # Or replaced with a new, possibly renamed value
                                else:
                                    new_values.append(new_options[option_id])

                            new_values = ",".join(new_values)
                            db.update("annotations", {"value": new_values}, where={"id": annotation_id})

        return count

    def __getattr__(self, attr):
        """
        Getter so we don't have to use .data all the time

        :param attr:  Data key to get
        :return:  Value
        """

        if attr in dir(self):
            # an explicitly defined attribute should always be called in favour
            # of this passthrough
            attribute = getattr(self, attr)
            return attribute
        elif attr in self.data:
            return self.data[attr]
        else:
            raise AttributeError("Annotation instance has no attribute %s" % attr)

    def __setattr__(self, attr, value):
        """
        Setter so we can flexibly update the database

        Also updates internal data stores (.data etc). If the attribute is
        unknown, it is stored within the 'metadata' attribute.

        :param str attr:  Attribute to update
        :param value:  New value
        """

        # don't override behaviour for *actual* class attributes
        if attr in dir(self):
            super().__setattr__(attr, value)
            return

        if attr not in self.data:
            self.metadata[attr] = value
            attr = "metadata"
            value = self.metadata

        if attr == "metadata":
            value = json.dumps(value)

        self.db.update("annotations", where={"id": self.id}, data={attr: value})

        self.data[attr] = value
        if attr == "metadata":
            self.metadata = json.loads(value)