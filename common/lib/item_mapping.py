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

    def get_item_data(self):
        """
        Get mapped item data
        :return dict:
        """
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
