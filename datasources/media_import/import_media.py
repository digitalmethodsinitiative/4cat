from backend.lib.processor import BasicProcessor
from common.lib.user_input import UserInput


class SearchMedia(BasicProcessor):
    type = "upload-media-search"  # job ID
    category = "Search"  # category
    title = "Upload Media"  # title displayed in UI
    description = "Upload your own audio, video, or image files to be used as a dataset"  # description displayed in UI
    extension = "zip"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    max_workers = 1

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        return {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "You can upload files here that will be available for further analysis "
                    "and processing. "
                    "You can indicate what type of files are uploaded (image, audio, or video) and based on that, "
                    "the 4CAT will be able to run various processors on these files. "
        },
        "data_upload": {
            "type": UserInput.OPTION_FILES,
            "help": "Files"
        },
        "format": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Media type",
            "options": {
                "audio": "Audio",
                "video": "Video",
                "image": "Images",
            },
            "default": "image"
        },
    }