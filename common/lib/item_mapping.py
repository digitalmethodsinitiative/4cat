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

    def __init__(self, data, message=""):
        """
        Constructor
        :param dict data:  Mapped item data
        :param str message:  Optionally, a message, e.g. a raised warning
        """
        self.data = data
        self.message = message

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
