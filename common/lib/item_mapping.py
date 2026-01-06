"""
Classes for mapped items, i.e. complex objects mapped to simple dictionaries
for 4CAT processing
"""


class MissingMappedField:
    """
    Class for a missing field in a mapped item

    Used if e.g. a metric is missing in the underlying data object, and
    processors might want to know this instead of using a default value
    """

    def __init__(self, default):
        """
        Constructor

        :param default:  Value to use as the value of this field unless the
        processor decides otherwise.
        """
        self.value = default


class MappedItem:
    """
    Class for mapped items

    Mapped items are complex objects mapped to simple dictionaries for 4CAT
    processing. But a dictionary has limited room for annotation, so this
    class allows for additionally passing messages, warnings, etc.
    """

    def __init__(self, data, message=""):
        """
        Constructor
        :param dict data:  Mapped item data
        :param str message:  Optionally, a message, e.g. a raised warning
        """
        self.data = data
        self.message = message
        self.missing = [k for k in self.data if type(self.data[k]) is MissingMappedField]

    def get_item_data(self, safe=False):
        """
        Get mapped item data

        :param bool safe:  Replace MissingMappedFields with their default value
        :return dict:
        """
        data = self.data.copy()

        # replace MissingMappedFields
        if safe:
            for field, value in data.items():
                if type(value) is MissingMappedField:
                    data[field] = value.value

        return self.data

    def get_message(self):
        """
        Get mapped item message
        :return str:
        """
        return self.message

    def get_missing_fields(self):
        """
        Get missing data fields
        :return list:
        """
        return self.missing


class DatasetItem(dict):
    """
    An item, from a dataset

    This is a dict, with two special properties: 'original' and 'mapped_object'
    which store the unmapped version of the item and the MappedItem
    representation of the item, respectively. These can be used as alternative
    views on the same data which may offer useful capabilities in some contexts.

    :todo: consider just-in-time mapping by only storing the original and
    calling the mapper only when the object is accessed as a dict
    """
    def __init__(self, mapper, original, mapped_object, *args, **kwargs):
        """
        DatasetItem init

        :param callable mapper:  Mapper for this item. Currently unused, could
        be used for above-mentioned just-in-time mapping.
        :param dict original:  Original item, e.g. from the csv or ndjson
        :param MappedItem|None mapped_object:  Mapped item, before resolving any
        potential missing data
        """
        super().__init__(*args, **kwargs)

        self._mapper = mapper
        self._original = original
        self._mapped_object = mapped_object

        if hasattr(mapped_object, "get_missing_fields"):
            self.missing_fields = mapped_object.get_missing_fields()
            self["missing_fields"] = ", ".join(self.missing_fields)

    @property
    def original(self):
        """
        Return original unmapped data

        :return dict:
        """
        return self._original

    @property
    def mapped_object(self):
        """
        Return mapped item object

        :return MappedItem:
        """
        return self._mapped_object
