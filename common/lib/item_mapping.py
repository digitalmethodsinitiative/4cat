class MappedItem:
    def __init__(self, data, message=""):
        self.data = data
        self.message = message

    def get_item_data(self):
        return self.data

    def get_message(self):
        return self.message
