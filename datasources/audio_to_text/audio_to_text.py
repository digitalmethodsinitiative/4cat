"""
Audio Upload to Text

This data source acts similar to a Preset, but because it needs SearchMedia's validate_query and after_create methods
to run, chaining that processor does not work (Presets essentially only run the process and after_process methods
of their processors and skip those two datasource only methods).
"""

from datasources.media_import.import_media import SearchMedia
from processors.machine_learning.whisper_speech_to_text import AudioToText


class AudioUploadToText(SearchMedia):
    type = "upload-audio-to-text-search"  # job ID
    category = "Search"  # category
    title = "Convert speech to text"  # title displayed in UI
    description = "Upload your own audio and use OpenAI's Whisper model to create transcripts"  # description displayed in UI

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        #TODO: False here does not appear to actually remove the datasource from the "Create dataset" page so technically
        # this method is not necessary; if we can adjust that behavior, it ought to function as intended

        # Ensure the Whisper model is available
        return AudioToText.is_compatible_with(module=module, config=config)

    @classmethod
    def get_options(cls, *args, **kwargs):
        # We need both sets of options for this datasource
        media_options = SearchMedia.get_options(*args, **kwargs)
        whisper_options = AudioToText.get_options(*args, **kwargs)
        media_options.update(whisper_options)

        #TODO: there are some odd formatting issues if we use those derived options
        # The intro help text is not displayed correct (does not wrap)
        # Advanced Settings uses []() links which do not work on the "Create dataset" page, so we adjust

        media_options["intro"]["help"] = ("Upload audio files here to convert speech to text. "
                        "4CAT will use OpenAI's Whisper model to create transcripts."
                        "\n\nFor information on using advanced settings: [Command Line Arguments (CLI)](https://github.com/openai/whisper/blob/248b6cb124225dd263bb9bd32d060b6517e067f8/whisper/transcribe.py#LL374C3-L374C3)")
        media_options["advanced"]["help"] = "Advanced Settings"

        return media_options

    @staticmethod
    def validate_query(query, request, config):
        # We need SearchMedia's validate_query to upload the media
        media_query = SearchMedia.validate_query(query, request, config)

        # Here's the real trick: act like a preset and add another processor to the pipeline
        media_query["next"] = [{"type": "audio-to-text",
                         "parameters": query.copy()}]
        return media_query