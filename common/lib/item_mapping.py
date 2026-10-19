"""
Classes for mapped items, i.e. complex objects mapped to simple dictionaries
for 4CAT processing
"""


class MissingMappedField:
    """
    Class for a missing field in a mapped item

    Used if e.g. a metric is missing in the underlying data object, and
    processors might want to know this instead of using a default value

    A field is missing when the source data holds no value for it. An absent
    key always means that: the source told us nothing about the field, so
    there is nothing to record. A value of zero, an empty string or false is a
    real value and belongs in the dataset as it is - a post with no likes and
    a post whose like count was never sent are different things, and only the
    second one is missing.

    A value of null sits between the two and cannot be decided here. It may
    mean the source has no value for the field, or it may mean the value
    genuinely is nothing: in one and the same platform response, a null author
    can mean the page left the author out, while a null location means the post
    has no location. Only the method mapping a particular platform's data can
    tell those apart, so each `map_item` decides what a null means for each of
    its own fields.

    The value processors fall back on when they do not handle missing data is
    the `default` given here, so pick one that cannot be mistaken for a real
    value. For a count that means -1 rather than 0.
    """

    def __init__(self, default):
        """
        Constructor

        :param default:  Value to use as the value of this field unless the
        processor decides otherwise.
        """
        self.value = default


def value_or_missing(source, key, default):
    """
    Read a field from source data, marking it missing if the key is not there

    An absent key means the source told us nothing about this field, so there
    is no value to record. Everything the source did send is returned as it
    is, including zero, an empty string, false and null.

    Null is deliberately left alone: whether it means "no value was
    collected" or "the value is nothing" depends on the field, so the calling
    `map_item` has to decide. Where a platform answers that the same way for
    most of its fields, say so once in that datasource rather than repeating
    the check.

    :param dict source:  Data to read the field from
    :param str key:  Name of the field to read
    :param default:  Value processors should fall back on if the field turns
      out to be missing; pick one that cannot pass for a real value
    :return:  The field's value, or a MissingMappedField if the key is absent
    """
    if key not in source:
        return MissingMappedField(default)

    return source[key]


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

        return data

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
    def __init__(self, mapper, original, mapped_object, data_file, *args, **kwargs):
        """
        DatasetItem init

        :param callable mapper:  Mapper for this item. Currently unused, could
          be used for above-mentioned just-in-time mapping.
        :param dict original:  Original item, e.g. from the csv or ndjson
        :param MappedItem mapped_object:  Mapped item, before resolving any
          potential missing data
        :param Path data_file:  Path to the file this item represents, if any,
          else `None`
        """
        super().__init__(*args, **kwargs)

        self._mapper = mapper
        self._original = original
        self._mapped_object = mapped_object
        self._file = data_file

        if hasattr(mapped_object, "get_missing_fields"):
            self.missing_fields = mapped_object.get_missing_fields()
            self["missing_fields"] = ", ".join(self.missing_fields)

    @property
    def file(self):
        """
        Return file path object, if relevant

        :return Path:
        """
        return self._file

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
