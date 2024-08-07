"""
Annotation class
"""

from common.config_manager import config

class Annotation:
    """
    Annotation class

    Annotations are always tied to a dataset and an item ID.

    """

    # Attributes must be created here to ensure getattr and setattr work properly

    data = None
    db = None

    id = ""                 # Unique ID for this annotation
    parent_id = ""          # ID of the data for this annotation, e.g. post ID
    dataset = ""            # Dataset key this annotation is generated from
    timestamp = 0           # When this annotation was edited
    timestamp_created = 0   # When this timestamp was created
    label = ""              # Label of annotation
    options = []            # Possible options
    value = ""              # The actual annotation value
    author = ""             # Who made the annotation
    by_processor = False    # Whether the annotation was made by a processor
    metadata = {}           # Misc metadata

    def __init__(self, db, data, id=None, item_id=None, label=None, dataset_key=None):
        """
        Instantiate annotation object.

        :param db:  Database connection object
        :param dict data:  Annotation data; should correspond to the annotations table records.

        """

        self.db = db
        self.data = data
        self.item_id = item_id

        if id is not None:
            self.id = id
            current = self.db.fetchone("SELECT * FROM annotations WHERE key = %s", (self.id,))
            if not current:
                raise AnnotationException(
                    "Annotation() requires a valid ID for its 'id' argument, \"%s\" given" % id)

        # Should be present for all annotation fields
        mandatory_keys = ["post_id", "label", "value"]


        if dataset_key is not None and label is not None and dataset_key is not None:
            current = self.db.fetchone("SELECT * FROM annotations WHERE key = %s", (self.key,))
            if not current:
                raise DataSetNotFoundException(
                    "DataSet() requires a valid dataset key for its 'key' argument, \"%s\" given" % key)


    def get_by_id(db, id):
        """
        Get annotation by ID

        :param db:  Database connection object
        :param str name:  ID of annotation
        :return:  Annotation object, or `None` for invalid annotation ID
        """
        data = db.fetchone("SELECT * FROM annotations WHERE id = %s", (id,))
        if not annotation:
            return None
        else:
            return Annotation.get_by_data(db, data)

    def get_by_data(db, data):
        """
        Instantiate annotation object with given data

        :param db:          Database handler
        :param dict data:   Annotation data, should correspond to a database row
        :return Annotation: Annotation object
        """
        return Annotation(db, data)

    def set_id_by_data(self, item):
        """
        Creates an ID based on the data of the item it has annotated.


        """


        return True

    def save(self):
        """
        Save an annotation to the database.
        """
        return True

    @staticmethod
    def save_many(self, annotations, overwrite=True):
        """
        Takes a list of annotations and saves them to the annotations table.
        If a field is not yet present in the datasets table, it also adds it there.

        :param bool overwrite:			Whether to overwrite annotation if the label is already present
                                        for the dataset.

        :returns int:					How many annotations were saved.

        """

        field_keys = {}
        annotations_to_delete = set()

        # We're going to add the annotation metadata to the datasets table
        # based on the annotations themselves.
        annotation_fields = self.get_annotation_fields()
        existing_annotations = self.get_annotations()
        existing_labels = set(a["label"] for a in existing_annotations) if existing_annotations else []

        timestamp = time.time()

        new_annotations = []
        for annotation in annotations:

            # Do some validation; dataset key, post_id, label, and value need to be present.
            missing_keys = []
            for mandatory_key in mandatory_keys:
                if mandatory_key not in annotation:
                    missing_keys.append(mandatory_key)
            if missing_keys:
                raise AnnotationException("Couldn't add annotations; missing field(s) %s" % ",".join(missing_keys))

            # Add dataset key
            annotation["dataset"] = self.key

            # Raise exception if this label is already present for this dataset
            # and we're not overwriting
            if not overwrite and annotation["label"] in existing_labels:
                raise AnnotationException("Couldn't save annotations; label %s already present")

            # If there's no type given, use 'text'
            if not annotation.get("type"):
                annotation["type"] = "text"

            # If there's no timestamp given, set it to the current time.
            if not "timestamp" in annotation:
                annotation["timestamp"] = timestamp
                annotation["timestamp_created"] = timestamp

            # If not already given, create an ID for this annotation
            # based on the label, type, and dataset key.
            if "field_id" not in annotation:
                field_id_base = "-".join(annotation["dataset"], annotation["label"], annotation.get("type", ""))
                field_id = int.from_bytes(field_id_base.encode(), "little")
                annotation["field_id"] = field_id

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