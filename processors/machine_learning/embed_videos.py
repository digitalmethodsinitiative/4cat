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
                   "Requires an embedding model that accepts video, such as Qwen3-VL-Embedding. Ollama cannot take "
                   "video yet (as of Nov. 2026), so models served there embed a **single frame** plus the "
                   "audio.")
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
            "ollama_info": {
                "type": UserInput.OPTION_INFO,
                "help": "Ollama's embedding endpoint does not accept video, and takes at most one image per item. "
                        "**Only one frame of each video is embedded**, together with the soundtrack if you include "
                        "it below. The visual side of the embedding therefore says nothing about how the video "
                        "changes over time. For that, use a model on an OpenAI-compatible server, which takes the "
                        "whole clip.",
                "requires": "model^=ollama",
            },
            "frame_position": {
                "type": UserInput.OPTION_TEXT,
                "help": "Frame to use (% into the video)",
                "default": 10,
                "min": 0,
                "max": 100,
                "coerce_type": int,
                "tooltip": "The percentage point of the frame will be used to represent the video",
                "requires": "model^=ollama",
            },
            "include_audio": {
                "type": UserInput.OPTION_TOGGLE,
                "help": "Include the soundtrack",
                "default": True,
                "tooltip": "Embed the audio along with the frame, as one vector. Videos with no audio track are "
                           "embedded from the frame alone.",
                "requires": "model^=ollama",
            },
            "audio_seconds": {
                "type": UserInput.OPTION_TEXT,
                "help": "Seconds of audio",
                "default": 75,
                "min": 5,
                "max": 80,
                "coerce_type": int,
                "tooltip": "Taken from the same point in the video as the frame. The model refuses more than about "
                           "80 seconds of audio in one request, whatever the context setting.",
                "requires": "include_audio==true",
            },
            "compression_info": {
                "type": UserInput.OPTION_INFO,
                "help": "Compression speeds up requests. Reducing the frame rate helps the most, and most models only "
                        "embed based on a few video frames anyway. Long or large videos can also exceed the model's "
                        "context window and be rejected.",
                "requires": "model!^=ollama",
            },
            "max_duration": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max seconds per video",
                "default": 30,
                "min": 1,
                "max": 600,
                "coerce_type": int,
                "tooltip": "Longer videos are cut off at this point.",
                "requires": "model!^=ollama",
            },
            "fps": {
                "type": UserInput.OPTION_TEXT,
                "help": "Frames per second",
                "default": 1,
                "min": 0.1,
                "max": 30,
                "coerce_type": float,
                "tooltip": "Match this to how many frames the model samples. Higher values mostly add bytes.",
                "requires": "model!^=ollama",
            },
            "max_size": {
                "type": UserInput.OPTION_TEXT,
                "help": "Max width/height in pixels",
                "default": 448,
                "min": 64,
                "max": 1920,
                "coerce_type": int,
                "tooltip": "Videos, or the single frame on Ollama, are scaled down to this, keeping their aspect "
                           "ratio.",
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
                "requires": "model!^=ollama",
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

    def single_frame_mode(self) -> bool:
        """
        Whether this run must reduce each video to one frame.

        :return bool:  True when the model is served by Ollama
        """
        return str(self.parameters.get("model", "")).startswith("ollama")

    def prepare_media(self, media_path, output_path) -> tuple:
        """
        Turn a video into something the chosen server can embed.

        :param Path media_path:  Video to prepare
        :param Path output_path:  Where to write the prepared media
        :return tuple:  `(descriptor or list of them, original size, sent size)`
        """
        if self.single_frame_mode():
            return self.prepare_frame_and_audio(media_path, output_path)

        return self.prepare_container(media_path, output_path)

    def prepare_frame_and_audio(self, media_path, output_path) -> tuple:
        """
        Reduce a video to one frame and, optionally, its soundtrack.

        Ollama takes at most one image and one audio clip per item, and no video
        container at all, so this is as much of a video as a single vector can
        represent there. Both are taken from the same point in the clip, so the
        two halves describe the same moment.

        :param Path media_path:  Video to prepare
        :param Path output_path:  Working path, whose stem is reused
        :return tuple:  `(list of descriptors, original size, sent size)`
        """
        position = self.parameters.get("frame_position", 10) / 100
        offset = self.probe_duration(media_path) * position

        frame_path = output_path.with_suffix(".frame.jpg")
        frame_path.unlink(missing_ok=True)
        result = self.run_interruptable_process([
            self.ffmpeg, "-y", "-ss", f"{offset:.3f}", "-i", str(media_path),
            "-frames:v", "1",
            "-vf", f"scale='min({self.parameters.get('max_size', 448)},iw)':-2",
            "-q:v", "3", str(frame_path),
        ], cleanup_paths=(frame_path,))

        if result.returncode != 0 or not frame_path.exists():
            raise RuntimeError(f"ffmpeg could not take a frame at {offset:.1f}s (exit {result.returncode})")

        payload = [{"type": "image", "mime": "image/jpeg", "data": self.encode(frame_path)}]
        sent_size = frame_path.stat().st_size
        frame_path.unlink(missing_ok=True)

        if self.parameters.get("include_audio", True):
            audio_path = output_path.with_suffix(".audio.wav")
            audio_path.unlink(missing_ok=True)
            # 16 kHz mono is what these models are trained on, and a shorter
            # clip than the model's ceiling keeps a long video from failing
            # outright
            audio_result = self.run_interruptable_process([
                self.ffmpeg, "-y", "-ss", f"{offset:.3f}", "-i", str(media_path),
                "-t", str(self.parameters.get("audio_seconds", 75)),
                "-vn", "-ac", "1", "-ar", "16000", str(audio_path),
            ], cleanup_paths=(audio_path,))

            if audio_result.returncode == 0 and audio_path.exists() and audio_path.stat().st_size:
                payload.append({"type": "audio", "mime": "audio/wav", "data": self.encode(audio_path)})
                sent_size += audio_path.stat().st_size
            else:
                # a silent clip, or one with no audio stream at all, is normal
                self.dataset.log(f"{media_path.name}: no audio track, embedding the frame alone")

            audio_path.unlink(missing_ok=True)

        original_size = media_path.stat().st_size
        self.dataset.log(f"{media_path.name}: frame at {offset:.1f}s"
                         f"{' + audio' if len(payload) > 1 else ''}, {sent_size / 1024:.0f} KB")

        return payload, original_size, sent_size

    def probe_duration(self, media_path) -> float:
        """
        Read a video's length, so a percentage can be turned into a timestamp.

        :param Path media_path:  Video to measure
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

    def prepare_container(self, media_path, output_path) -> tuple:
        """
        Re-encode the whole video smaller and return it as one descriptor.

        Audio is dropped here: a server that takes a video container reads the
        visual track only, and the soundtrack would just be bytes it discards.

        :param Path media_path:  Video to prepare
        :param Path output_path:  Where to write the re-encoded video
        :return tuple:  `(media descriptor, original size, sent size)`
        """
        output_path.unlink(missing_ok=True)

        command = [
            self.ffmpeg, "-y", "-i", oslex.quote(str(media_path)),
            "-t", str(self.parameters.get("max_duration", 30)),
            # scale down only if the video is larger; -2 keeps the other side
            # even, which H.264 requires. tpad repeats the last frame once: a
            # clip of a second or less otherwise ends up as a single frame.
            "-vf", f"scale='min({self.parameters.get('max_size', 448)},iw)':-2,fps={self.parameters.get('fps', 1)},"
                   f"tpad=stop_mode=clone:stop=1",
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
