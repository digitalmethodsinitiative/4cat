"""
Class for mapped items, i.e. complex objects mapped to simple dictionaries for
4CAT processing
"""


class MappedItem:
    """
    Class for mapped items

    Mapped items are complex objects mapped to simple dictionaries for 4CAT
    processing. But a dictionary has limited room for annotation, so this
    class allows for additionally passing messages, warnings, etc.
    """

    def __init__(self, data, message="", missing=None):
        """
        Constructor
        :param dict data:  Mapped item data
        :param str message:  Optionally, a message, e.g. a raised warning
        :param list|None missing:  List of fields in the mapped data dictionary
        that were missing or incompatible in the underlying data. This can be
        used by processors to decide how to deal with the data
        """
        if missing is None:
            missing = []

        self.data = data
        self.message = message
        self.missing = missing

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
