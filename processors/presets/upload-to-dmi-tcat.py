"""
Upload Twitter dataset to DMI-TCAT instance
"""
from backend.lib.preset import ProcessorPreset
from common.lib.helpers import UserInput

class FourcatToDmiTcatConverterAndUploader(ProcessorPreset):
    """
    Run processor pipeline to extract neologisms
    """
    type = "preset-upload-tcat"  # job type ID
    category = "Combined processors"  # category. 'Combined processors' are always listed first in the UI.
    title = "Upload to DMI-TCAT"  # title displayed in UI
    description = "Convert the dataset to a TCAT-compatible format and upload it to an available TCAT server."  # description displayed in UI
    extension = "html"

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        Give the user the choice of where to upload the dataset, if multiple
        TCAT servers are configured. Otherwise, no options are given since
        there is nothing to choose.

        :param config:
        :param DataSet parent_dataset:  Dataset that will be uploaded
        """
        if config.get('tcat-auto-upload.server_url') \
                and type(config.get('tcat-auto-upload.server_url')) in (set, list, tuple) \
                and len(config.get('tcat-auto-upload.server_url')) > 1:
            return {
                "server": {
                    "type": UserInput.OPTION_CHOICE,
                    "options": {
                        "random": "Choose one based on available capacity",
                        **{
                            url: url for url in config.get('tcat-auto-upload.server_url')
                        }
                    },
                    "default": "random",
                    "help": "Server to upload to",
                    "tooltip": "Which TCAT server to upload the dataset to. If you do not choose one, 4CAT will "
                               "upload the dataset to the server with the highest available capacity."
                }
                # todo: actually make it choose one that way instead of choosing at random
            }
        else:
            return {}

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Determine if processor is compatible with dataset

        :param module: Dataset or processor to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return module.type == "twitterv2-search" and \
               config.get('tcat-auto-upload.server_url') and \
               config.get('tcat-auto-upload.token') and \
               config.get('tcat-auto-upload.username') and \
               config.get('tcat-auto-upload.password')

    def get_processor_pipeline(self):
        """
        This queues a series of post-processors to upload a dataset to a
        DMI-TCAT instance.
        """

        pipeline = [
            # first, convert to import-able format
            {
                "type": "convert-ndjson-for-tcat",
                "parameters": {}
            },
            # then, upload it
            {
                "type": "tcat-auto-upload",
                "parameters": {"server": self.parameters.get("server", "random")}
            }
        ]

        return pipeline
