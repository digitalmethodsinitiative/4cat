"""
Annotation class
"""


import time
import json

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
    options = None            # Possible options
    value = None              # The actual annotation value
    author = None             # Who made the annotation
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
        if id is None and (data is None or not isinstance(data, dict)):
            raise AnnotationException("Annotation() requires either a `data` dictionary or ID.")

        if not db:
            raise AnnotationException("Annotation() needs a `db` database object")

        self.db = db

        current = None
        new_or_updated = False

        # Get the annotation data if the ID is given; if an annotation has
        # an ID, it is guaranteed to be in the database.
        # IDs can both be explicitly given or present in the data dict.
        if id is not None or "id" in data:
            if "id" in data:
                id = data["id"]
            self.id = id # IDs correspond to unique serial numbers in the database.
            current = self.db.fetchone("SELECT * FROM annotations WHERE id = %s" % (self.id))
            if not current:
                raise AnnotationException(
                    "Annotation() requires a valid ID for its 'id' argument, %s given" % id)

        # If an ID is not given, get or create an Annotation object from its data.
        # First check if required fields are present in `data`.
        else:
            for required_field in required_fields:
                if required_field not in data or not data[required_field]:
                    raise AnnotationException("Annotation() requires a %s field" % required_field)

            # Check if this annotation already exists, based on the data
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
                    # Else update the value
                    elif current[key] != value:
                        current[key] = value
                        new_or_updated = True

            self.data = current

        # If this is a new annotation, set all the properties.
        else:
            # Keep track of when the annotation was made
            created_timestamp = int(time.time())
            # Store unknown properties in `metadata`
            metadata = {k: v for k, v in data.items() if k not in self.__dict__}
            print(self.__dict__)
            print(metadata)
            new_data = {
                "item_id": data["item_id"],
                "field_id": data["field_id"] if data.get("field_id") else self.get_field_id(data["dataset"], data["label"]),
                "dataset": data["dataset"],
                "timestamp_created": timestamp,
                "label": data["label"],
                "type": data.get("type", "text"),
                "options": data.get("options", ""),
                "value": data.get("value", ""),
                "author": data.get("author", ""),
                "by_processor": data.get("by_processor", False),
                "metadata": metadata
            }
            self.data = new_data
            new_or_updated = True

        # Write to db if anything changed
        if new_or_updated:
            timestamp = int(time.time())
            self.timestamp = timestamp
            self.write_to_db()

    def get_by_id(self, id):
        """
        Get annotation by ID

        :param str name:  ID of annotation
        :return:  Annotation object, or `None` for invalid annotation ID
        """

        try:
            int(id)
        except ValueError:
            raise AnnotationException("Id '%s' is not valid" % id)

        return Annotation(id=id)

    def get_by_field(self, dataset_key, item_id, label):
        """
        Get the annotation information via its dataset key, item ID, and label.
        This is always a unique comibination.

        :param dataset_key:     The key of the dataset this annotation was made for.
        :param item_id:         The ID of the item this annotation was made for.
        :param label:           The label of the annotation.

        :return data: A dict with data of the retrieved annotation, or None if it doesn't exist.
        """

        data = self.db.fetchone("SELECT * FROM annotations WHERE dataset = %s AND item_id = %s AND label = %s",
                         (dataset_key, item_id, label))
        if not data:
            return None

        data["metadata"] = json.loads(data["metadata"])
        return data

    def get_field_id(self, dataset_key, label):
        """
        Sets a `field_id` based on the dataset key and label.
        This combination should be unique.

        :param dataset_key: The dataset key
        :param label:       The label of the dataset.
        """
        field_id_base = "-".join([dataset_key, label])
        field_id = int.from_bytes(field_id_base.encode(), "little")
        self.field_id = field_id
        return field_id

    def write_to_db(self):
        """
        Write an annotation to the database.
        """
        data = self.data
        data["metadata"] = json.dumps(data["metadata"])
        return self.db.upsert("annotations", data=data, constraints=["dataset", "label", "item_id"])

    @staticmethod
    def save_many(self, annotations, overwrite=True):
        """
        Takes a list of annotations and saves them to the annotations table.
        If a field is not yet present in the datasets table, it also adds it there.

        :param bool overwrite:			Whether to overwrite annotation if the label is already present
                                        for the dataset.

        :returns int:					How many annotations were saved.

        """
        new_annotations = []
        for annotation in annotations:
            # Add annotation metadata if it is not saved to the datasets table yet.
            # This is just a simple dict with a field ID, type, label, and possible options.
            if annotation["field_id"] not in annotation_fields:
                annotation_fields[annotation["field_id"]] = {
                    "label": annotation["label"],
                    "type": annotation["type"]
                }
                if "options" in annotation:
                    annotation_fields[annotation["field_id"]]["options"] = annotation["options"]

            new_annotations.append(annotation)

        # Save annotation fields if they're not present yet.
        if annotation_fields != self.get_annotation_fields():
            self.save_annotation_fields(annotation_fields)

        # If there's nothing to save or delete, do nothing
        if not new_annotations:
            return 0

        # Overwrite old annotations with upsert. Else add.
        self.db.upsert("annotations", new_annotations, constraints=["dataset", "post_id", "label"])

        return len(new_annotations)

    def delete(self):
        """
        Deletes this annotation
        """
        return self.db.delete("annotations", {"id": self.id})

    @staticmethod
    def delete_many(self, dataset_key=None, id=None, field_id=None):
        """
        Deletes annotations for an entire dataset or by a list of (field) IDs.

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

        return self.db.delete("annotations", where)

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
            self.parameters[attr] = value
            attr = "metadata"
            value = self.parameters

        if attr == "metadata":
            value = json.dumps(value)

        self.db.update("annotations", where={"id": self.id}, data={attr: value})

        self.data[attr] = value

        if attr == "metadata":
            self.parameters = json.loads(value)