"""
Generate an embedding per video via a multimodal embedding model.
"""
import shutil

import oslex

from common.lib.compatibility import Compatibility, is_executable
from common.lib.user_input import UserInput
from processors.machine_learning.embed_media import EmbedMedia

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"


class EmbedVideos(EmbedMedia):
    """
    Send each video to a multimodal embedding model and store the vector it
    returns, so videos can be compared, mapped and searched by content.
    """
    type = "video-embeddings"  # job type ID
    category = "Visual"  # category
    title = "Generate video embeddings"  # title displayed in UI
    description = ("Generate a numerical representation (an 'embedding') of each video using a multimodal embedding "
                   "model. This allows videos to be compared and clustered. Videos are compressed before sending. "
                   "Requires an embedding model that accepts video, such as Qwen3-VL-Embedding.")
    extension = "ndjson"  # extension of result file, used internally and in UI

    media_label = "video"
    media_label_plural = "videos"
    model_requirement_note = "not only text or images"
    working_filename = "compressed.mp4"
    annotation_label = "video embedding"

    compatibility = Compatibility(
        media_types={"video"},
        type_prefixes={"video-downloader"},
        required_settings={("video-downloader.ffmpeg_path", is_executable)},
        preferred_followups=["reduce-embeddings", "cluster-embeddings", "embedding-similarity"],
    )

    references = [
        "[Qwen3-VL-Embedding](https://qwen.ai/blog?id=qwen3-vl-embedding)",
        "[Qwen3-VL-Embedding and Qwen3-VL-Reranker (arXiv:2601.04720)](https://arxiv.org/abs/2601.04720)",
    ]

    @classmethod
    def get_media_options(cls, config=None) -> dict:
        """
        Options controlling how a video is made smaller before it is sent.

        :param ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:  Options for this processor
        """
        return {
            "compression_info": {
                "type": UserInput.OPTION_INFO,
                "help": "Compression speeds up requests. Reducing the frame rate helps the most, and most models only "
                        "embed based on a few video frames anyway. Long or large videos can also exceed the model's "
                        "context window and be rejected.",
            },
            "max_duration": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max seconds per video",
                "default": 30,
                "min": 1,
                "max": 600,
                "coerce_type": int,
                "tooltip": "Longer videos are cut off at this point.",
            },
            "fps": {
                "type": UserInput.OPTION_TEXT,
                "help": "Frames per second",
                "default": 1,
                "min": 0.1,
                "max": 30,
                "coerce_type": float,
                "tooltip": "Match this to how many frames the model samples. Higher values mostly add bytes.",
            },
            "max_size": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max width/height in pixels",
                "default": 448,
                "min": 64,
                "max": 1920,
                "coerce_type": int,
                "tooltip": "Videos larger than this are scaled down, keeping their aspect ratio.",
            },
            "crf": {
                "type": UserInput.OPTION_TEXT,
                "help": "Compression level",
                "default": 32,
                "min": 0,
                "max": 51,
                "coerce_type": int,
                "tooltip": "Min: 0, max: 51. H.264 CRF: higher means smaller files and lower quality. 23 is visually "
                           "lossless, 32 is a reasonable trade-off, above 40 makes the video grainy.",
            },
        }

    def check_requirements(self) -> str | None:
        """
        Resolve ffmpeg, which does the re-encoding.

        :return str|None:  An error message, or `None` when ffmpeg is present.
        """
        self.ffmpeg = shutil.which(self.config.get("video-downloader.ffmpeg_path"))
        if not self.ffmpeg:
            return "ffmpeg is not available, so videos cannot be prepared for embedding."

        return None

    def prepare_media(self, media_path, output_path) -> tuple:
        """
        Re-encode a video smaller and return it as a base64 media descriptor.
        Audio is dropped outright since these are vision-language models and never read it.

        :param Path media_path:  Video to prepare
        :param Path output_path:  Where to write the re-encoded video
        :return tuple:  `(media descriptor, original size, sent size)`
        """
        output_path.unlink(missing_ok=True)

        command = [
            self.ffmpeg, "-y", "-i", oslex.quote(str(media_path)),
            "-t", str(self.parameters.get("max_duration", 30)),
            # scale down only if the video is larger; -2 keeps the other side
            # even, which H.264 requires
            "-vf", f"scale='min({self.parameters.get('max_size', 448)},iw)':-2,fps={self.parameters.get('fps', 1)}",
            "-c:v", "libx264",
            "-crf", str(self.parameters.get("crf", 32)),
            "-preset", "veryfast",
            "-an",
            "-movflags", "+faststart",
            oslex.quote(str(output_path)),
        ]

        result = self.run_interruptable_process(command, cleanup_paths=(output_path,))
        if result.returncode != 0 or not output_path.exists():
            error = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
            raise RuntimeError(f"ffmpeg exited {result.returncode}: {' '.join(error.split(chr(10))[-2:])}")

        original_size = media_path.stat().st_size
        sent_size = output_path.stat().st_size
        self.dataset.log(f"{media_path.name}: {original_size / 1024:.0f} KB -> {sent_size / 1024:.0f} KB")

        payload = {"type": "video", "mime": "video/mp4", "data": self.encode(output_path)}
        output_path.unlink(missing_ok=True)

        return payload, original_size, sent_size
