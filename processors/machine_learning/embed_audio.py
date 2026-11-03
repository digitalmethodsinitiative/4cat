"""
Generate an embedding per audio file via a multimodal embedding model.
"""
import shutil

from common.lib.compatibility import Compatibility, is_executable
from common.lib.user_input import UserInput
from processors.machine_learning.embed_media import EmbedMedia

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class EmbedAudio(EmbedMedia):
    """
    Send each audio file to a multimodal embedding model and store the vector it
    returns, so recordings can be compared, mapped and searched by how they
    sound.
    """
    type = "audio-embeddings"  # job type ID
    category = "Audio"  # category
    title = "Generate audio embeddings"  # title displayed in UI
    description = ("Generate a numerical representation (an 'embedding') of each audio file using an "
                   "embedding model. This allows recordings to be compared and clustered by how they sound. Requires "
                   "an embedding model that accepts audio.")
    extension = "ndjson"  # extension of result file, used internally and in UI

    media_label = "audio file"
    media_label_plural = "audio files"
    model_requirement_note = "not only text or images"
    working_filename = "prepared.wav"
    annotation_label = "audio embedding"

    compatibility = Compatibility(
        media_types={"audio"},
        type_prefixes={"audio-extractor"},
        required_settings={("video-downloader.ffmpeg_path", is_executable)},
        preferred_followups=["reduce-embeddings", "cluster-embeddings", "embedding-similarity"],
    )

    references = [
        "[EmbeddingGemma 2](https://huggingface.co/google/embeddinggemma-2)",
    ]

    @classmethod
    def get_media_options(cls, config=None) -> dict:
        """
        Options controlling which part of the audio is sent.

        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:  Options for this processor
        """
        return {
            "window_info": {
                "type": UserInput.OPTION_INFO,
                "help": "Audio embedding models usually only accept a short stretch of audio (often around 80 seconds). "
                        "Longer recordings are cut down to the window below.",
            },
            "window_position": {
                "type": UserInput.OPTION_TEXT,
                "help": "Audio start %",
                "default": 0,
                "min": 0,
                "max": 100,
                "coerce_type": int,
                "tooltip": "The percentage point of where the audio starts.",
            },
            "window_seconds": {
                "type": UserInput.OPTION_TEXT,
                "help": "Seconds of audio",
                "default": 75,
                "min": 5,
                "max": 80,
                "coerce_type": int,
                "tooltip": "Length of the audio fragments to embed. Max: 80s. Min: 5s.",
            },
        }

    def check_requirements(self) -> str | None:
        """
        Resolve ffmpeg, which trims and resamples the audio.

        :return str|None:  An error message, or `None` when ffmpeg is present.
        """
        self.ffmpeg = shutil.which(self.config.get("video-downloader.ffmpeg_path"))
        if not self.ffmpeg:
            return "ffmpeg is not available, so audio cannot be prepared for embedding."

        return None

    def prepare_media(self, media_path, output_path) -> tuple:
        """
        Trim a window out of the audio and return it as a base64 descriptor.

        Resampled to 16 kHz mono, which is what these models are trained on, and
        what makes the clip small enough to travel inside the request.

        :param Path media_path:  Audio file to prepare
        :param Path output_path:  Where to write the trimmed clip
        :return tuple:  `(media descriptor, original size, sent size)`
        """
        output_path.unlink(missing_ok=True)

        position = self.parameters.get("window_position", 10) / 100
        offset = self.probe_duration(media_path) * position

        result = self.run_interruptable_process([
            self.ffmpeg, "-y", "-ss", f"{offset:.3f}", "-i", str(media_path),
            "-t", str(self.parameters.get("window_seconds", 75)),
            "-vn", "-ac", "1", "-ar", "16000", str(output_path),
        ], cleanup_paths=(output_path,))

        if result.returncode != 0 or not output_path.exists() or not output_path.stat().st_size:
            error = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            raise RuntimeError(f"ffmpeg exited {result.returncode}: {' '.join(error.split(chr(10))[-2:])}")

        original_size = media_path.stat().st_size
        sent_size = output_path.stat().st_size
        self.dataset.log(f"{media_path.name}: {self.parameters.get('window_seconds', 75)}s from {offset:.1f}s, "
                         f"{original_size / 1024:.0f} KB -> {sent_size / 1024:.0f} KB")

        payload = {"type": "audio", "mime": "audio/wav", "data": self.encode(output_path)}
        output_path.unlink(missing_ok=True)

        return payload, original_size, sent_size

    def probe_duration(self, media_path) -> float:
        """
        Read a recording's length, so a percentage becomes a timestamp.

        :param Path media_path:  File to measure
        :return float:  Length in seconds, or 0.0 when it cannot be read
        """
        ffprobe = shutil.which("ffprobe".join(self.ffmpeg.rsplit("ffmpeg", 1))) if self.ffmpeg else None
        if not ffprobe:
            return 0.0

        probe = self.run_interruptable_process([
            ffprobe, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(media_path),
        ])

        try:
            return float(probe.stdout.decode("utf-8", errors="replace").strip())
        except (ValueError, AttributeError):
            # an unreadable duration is not worth failing over; start at 0
            return 0.0
