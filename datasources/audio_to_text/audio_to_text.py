"""
Audio Upload to Text

This data source acts similar to a Preset, but because it needs SearchMedia's validate_query and after_create methods
to run, chaining that processor does not work (Presets essentially only run the process and after_process methods
of their processors and skip those two datasource only methods).
"""

from datasources.media_import.import_media import SearchMedia
from processors.machine_learning.audio_to_text import AudioToText


class AudioUploadToText(SearchMedia):
    type = "upload-audio-to-text-search"  # job ID
    category = "Search"  # category
    title = "Convert speech to text"  # title displayed in UI
    description = "Upload your own audio and use OpenAI's Whisper or GPT models to create transcripts"  # description displayed in UI

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        return AudioToText.is_compatible_with(module=module, config=config)

    @classmethod
    def get_options(cls, *args, **kwargs):
        # We need both sets of options for this datasource
        media_options = SearchMedia.get_options(*args, **kwargs)
        audio_to_text_options = AudioToText.get_options(*args, **kwargs)
        media_options.update(audio_to_text_options)
        return media_options

    @staticmethod
    def validate_query(query, request, config):
        # We need SearchMedia's validate_query to upload the media
        media_query = SearchMedia.validate_query(query, request, config)

        # Here's the real trick: act like a preset and add another processor to the pipeline
        media_query["next"] = [{"type": "audio-to-text",
                         "parameters": query.copy()}]
        return media_query