"""
Upload Twitter dataset to DMI-TCAT instance
"""
from backend.abstract.preset import ProcessorPreset

import config

class FourcatToDmiTcatConverterAndUploader(ProcessorPreset):
    """
    Run processor pipeline to extract neologisms
    """
    type = "preset-upload-tcat"  # job type ID
    category = "Presets"  # category. 'Presets' are always listed first in the UI.
    title = "Upload to DMI-TCAT"  # title displayed in UI
    description = "Convert the dataset to a format compatible with DMI-TCAT and upload it to an available instance."  # description displayed in UI
    extension = "svg"

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Determine if processor is compatible with dataset

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type == "twitterv2-search" and \
               hasattr(config, 'TCAT_SERVER') and \
               config.TCAT_SERVER and \
               hasattr(config, 'TCAT_TOKEN') and \
               hasattr(config, 'TCAT_USERNAME') and \
               hasattr(config, 'TCAT_PASSWORD')

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
                "parameters": {}
            }
        ]

        return pipeline
