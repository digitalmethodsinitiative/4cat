from unittest.mock import MagicMock

import pytest
import requests
from yt_dlp import DownloadError

from backend.lib.proxied_requests import FailedProxiedRequest
from processors.visualisation import download_videos
from processors.visualisation.download_videos import LiveVideoException, VideoDownloaderPlus
from processors.visualisation.download_weibo_videos import WeiboVideoDownloader


"""
When the video downloader gives up early.

The downloader stops when a run of links fails in the same way, so that a
dataset full of dead or refused links does not keep it busy for hours:
- 5 refusals (HTTP 403) or timeouts in a row, e.g. because the links have
  expired or the website is blocking us;
- 10 links in a row from the same website that are not videos.

These tests feed the real download code made-up answers; no requests are
actually made.
"""


class FakeResponse:
    """An answer from a website, as the proxied requests give them"""
    def __init__(self, status_code=200, content_type="video/mp4", body=b"video"):
        self.status_code = status_code
        self.reason = "Forbidden" if status_code == 403 else "OK"
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        self.body = body

    def iter_content(self, chunk_size=1):
        yield self.body

    def close(self):
        pass


VIDEO = FakeResponse()
DENIED = FakeResponse(status_code=403, content_type="text/html")
WEB_PAGE = FakeResponse(content_type="text/html")
TIMEOUT = FailedProxiedRequest(requests.exceptions.Timeout("timed out"))


def make_downloader(answers):
    """A video downloader that gets the given answers, in order, for the links it requests"""
    downloader = VideoDownloaderPlus.__new__(VideoDownloaderPlus)
    downloader.dataset = MagicMock()
    downloader.config = MagicMock()
    downloader.config.get.side_effect = lambda key, default=None, **kwargs: default
    downloader.interrupted = False
    downloader.downloaded_videos = 0
    downloader.total_possible_videos = len(answers)
    downloader.warning_message = None
    downloader.flush_proxied_requests = MagicMock()
    downloader.iterate_proxied_requests = lambda urls, **kwargs: zip(urls, answers)
    return downloader


def download_directly(answers, tmp_path, domains=None, also_indirect="none", ignore_not_video=False):
    """
    Run the direct download step

    :param list answers:  One website answer per link
    :param list domains:  Website of each link; all links are on the same website if not given
    :return tuple:  The downloader, the step's results, and what was noted per link
    """
    domains = domains or ["video.example.com"] * len(answers)
    urls = [f"https://{domain}/{number}.mp4" for number, domain in enumerate(domains)]
    urls_dict = {url: {"success": False, "retry": True} for url in urls}
    downloader = make_downloader(answers)
    results = downloader._process_direct_downloads(
        urls, urls_dict, tmp_path, max_video_size=100, also_indirect=also_indirect, amount=0,
        last_domains=[], ignore_not_video=ignore_not_video
    )
    return downloader, results, urls_dict


# --- direct downloads --------------------------------------------------------------

def test_refused_links_stop_after_five(tmp_path):
    """Expired links, as in a Weibo dataset downloaded days after it was collected"""
    downloader, results, _ = download_directly([DENIED] * 20, tmp_path)

    assert results["stop_reason"] == "errors"
    assert results["processed"] == 5
    assert results["failed"] == 5
    assert results["not_a_video_total"] == 0
    assert "working links" in downloader.warning_message


def test_refused_links_can_be_tried_again(tmp_path):
    _, _, urls_dict = download_directly([DENIED], tmp_path)

    url_info = next(iter(urls_dict.values()))
    assert url_info["retry"]
    assert "403" in url_info["error"]


def test_refusals_do_not_blame_the_non_direct_setting(tmp_path):
    # yt-dlp is only used for YouTube links here, so it played no part in these refusals
    downloader, results, _ = download_directly([DENIED] * 5, tmp_path, also_indirect="yt_only")

    assert results["stop_reason"] == "errors"
    assert "non-direct" not in downloader.warning_message


def test_refused_links_go_to_yt_dlp_when_allowed(tmp_path):
    _, results, _ = download_directly([DENIED] * 8, tmp_path, also_indirect="all")

    assert not results["stop_processing"]
    assert results["failed"] == 0
    assert len(results["ytdlp_queue"]) == 8


def test_a_video_in_between_resets_the_count(tmp_path):
    _, results, _ = download_directly([DENIED] * 4 + [VIDEO] + [DENIED] * 4, tmp_path)

    assert not results["stop_processing"]
    assert results["processed"] == 9
    assert results["failed"] == 8


def test_timeouts_stop_after_five(tmp_path):
    _, results, _ = download_directly([TIMEOUT] * 8, tmp_path)

    assert results["stop_reason"] == "errors"
    assert results["processed"] == 5


def test_web_pages_from_one_website_stop_after_ten(tmp_path):
    _, results, _ = download_directly([WEB_PAGE] * 15, tmp_path)

    assert results["stop_reason"] == "no-videos"
    assert results["processed"] == 10
    assert results["not_a_video_total"] == 10


def test_web_pages_from_different_websites_do_not_stop(tmp_path):
    domains = [f"site{number % 3}.example.com" for number in range(15)]
    _, results, _ = download_directly([WEB_PAGE] * 15, tmp_path, domains=domains)

    assert not results["stop_processing"]
    assert results["processed"] == 15


def test_ignoring_non_videos_does_not_stop(tmp_path):
    _, results, _ = download_directly([WEB_PAGE] * 15, tmp_path, ignore_not_video=True)

    assert not results["stop_processing"]
    assert results["processed"] == 15


# --- yt-dlp downloads --------------------------------------------------------------

SITE_ERROR = {"success": False, "site_error": True}
SETTINGS_ERROR = {"success": False, "site_error": False}
DOWNLOADED = {"success": True, "site_error": False}


def download_with_ytdlp(outcomes, tmp_path, in_preset=False):
    """
    Run the yt-dlp download step

    :param list outcomes:  What downloading each link with yt-dlp results in
    :param bool in_preset:  Whether the downloader runs as part of a preset, e.g. for TikTok or Weibo
    :return tuple:  The downloader and the step's results
    """
    urls = [f"https://www.youtube.com/watch?v={number}" for number in range(len(outcomes))]
    urls_dict = {url: {"success": False, "retry": True} for url in urls}
    downloader = make_downloader([])
    downloader.is_running_in_preset = in_preset
    downloader._download_single_ytdlp = MagicMock(side_effect=outcomes)
    results = downloader._process_ytdlp_downloads(
        urls, urls_dict, {}, tmp_path, amount=0, also_indirect="all", consecutive_errors=0
    )
    return downloader, results


def test_yt_dlp_errors_stop_after_five(tmp_path):
    downloader, results = download_with_ytdlp([SITE_ERROR] * 8, tmp_path)

    assert results["processed"] == 5
    assert "non-direct" in downloader.warning_message


def test_presets_do_not_suggest_changing_the_non_direct_setting(tmp_path):
    # the TikTok and Weibo presets turn yt-dlp on themselves; users cannot change that
    downloader, results = download_with_ytdlp([SITE_ERROR] * 5, tmp_path, in_preset=True)

    assert results["processed"] == 5
    assert "non-direct" not in downloader.warning_message
    assert "working links" in downloader.warning_message


def test_yt_dlp_errors_caused_by_settings_do_not_stop(tmp_path):
    # e.g. every video is larger than the maximum size
    _, results = download_with_ytdlp([SETTINGS_ERROR] * 8, tmp_path)

    assert results["processed"] == 8
    assert results["failed"] == 8


def test_yt_dlp_download_resets_the_count(tmp_path):
    _, results = download_with_ytdlp([SITE_ERROR] * 4 + [DOWNLOADED] + [SITE_ERROR] * 4, tmp_path)

    assert results["processed"] == 9


@pytest.mark.parametrize("error, is_site_error", [
    (DownloadError("ERROR: [Weibo] RnIE07YSu: HTTP Error 403: Forbidden"), True),
    (DownloadError("ERROR: [youtube] abc123: Requested format is not available"), False),
    (LiveVideoException("4CAT settings do not allow downloading live videos with this processor"), False),
])
def test_which_yt_dlp_errors_count(error, is_site_error, monkeypatch):
    class FakeYoutubeDL:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url):
            raise error

    monkeypatch.setattr(download_videos.yt_dlp, "YoutubeDL", FakeYoutubeDL)
    downloader = make_downloader([])
    url = "https://weibo.com/1886903325/RnIE07YSu"

    result = downloader._download_single_ytdlp(url, {}, {url: {}})

    assert not result["success"]
    assert result["site_error"] == is_site_error


# --- which links are collected -----------------------------------------------------

class FakeSource:
    """A dataset to download videos for, giving its mapped items"""
    def __init__(self, items):
        self.items = items
        self.num_rows = len(items)

    def iterate_items(self, processor=None, **kwargs):
        yield from self.items


VIDEO_POST = {
    "id": "1",
    "video_url": "https://f.video.weibocdn.com/o0/WTuS30b8lx08BKpeRPu001041200QWY50E010.mp4?label=mp4_720p&Expires=1792590895",
    "url": "https://weibo.com/1886903325/RnIE07YSu",
}
TEXT_POST = {"id": "2", "video_url": "", "url": "https://weibo.com/2172061270/RnnJA9tPy"}


def collect_links(items, parameters):
    """
    Collect the links the downloader would try

    :return tuple:  Video links, and post URLs that only yt-dlp is asked about
    """
    downloader = make_downloader([])
    downloader.source_dataset = FakeSource(items)
    downloader.parameters = parameters
    return downloader.collect_video_urls()


def test_posts_without_video_link_go_to_yt_dlp_by_default():
    """As for TikTok, where every post that is left at this point has a video"""
    urls, fallback_only = collect_links([VIDEO_POST, TEXT_POST], {"columns": ["video_url"], "_ytdlp_fallback_column": "url"})

    assert len(urls) == 1
    assert list(fallback_only) == [TEXT_POST["url"]]


def test_weibo_posts_without_video_are_left_out():
    weibo = WeiboVideoDownloader.__new__(WeiboVideoDownloader)
    weibo.parameters = {"amount": 100, "max_video_size": 100}
    parameters = weibo.get_processor_pipeline()[0]["parameters"]

    urls, fallback_only = collect_links([VIDEO_POST, TEXT_POST], parameters)

    # the video link is tried first; if it no longer works, yt-dlp gets the post's page
    assert [link_info["_ytdlp_fallback_url"] for link_info in urls.values()] == [VIDEO_POST["url"]]
    assert not fallback_only


# --- which downloader is offered ---------------------------------------------------

class FakeDataset:
    """Just enough of a dataset to check which processors are offered for it"""
    def __init__(self, type):
        self.type = type

    def is_top_dataset(self):
        return True

    def is_from_collector(self):
        return True

    def get_extension(self):
        return "ndjson"


def test_weibo_datasets_get_the_weibo_downloader():
    weibo = FakeDataset("weibo-search")

    assert WeiboVideoDownloader.is_compatible_with(weibo, config=MagicMock())
    assert not VideoDownloaderPlus.is_compatible_with(weibo, config=MagicMock())
    # other data sources still get the general one
    assert VideoDownloaderPlus.is_compatible_with(FakeDataset("douyin-search"), config=MagicMock())
