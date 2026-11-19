from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests
from yt_dlp import DownloadError
from yt_dlp.utils import ExistingVideoReached

from backend.lib.proxied_requests import DelegatedRequestHandler, FailedProxiedRequest, NoProxiesAvailableError
from processors.visualisation import download_videos
from common.lib.exceptions import ProcessorException
from common.lib.helpers import UniqueFilenames
from processors.visualisation.download_tiktok_video import TikTokVideoDownloader
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


class FakeSource:
    """A dataset to download videos for, giving its mapped items"""
    def __init__(self, items, media_request_headers=None):
        self.items = items
        self.num_rows = len(items)
        self.media_request_headers = media_request_headers or {}

    def iterate_items(self, processor=None, **kwargs):
        yield from self.items

    def get_media_request_headers(self):
        return dict(self.media_request_headers)


class FakeProxyPool:
    """4CAT's shared proxies, lending out the same proxy every time"""
    def __init__(self, proxy=DelegatedRequestHandler.PROXY_LOCALHOST):
        self.proxy = proxy
        self.borrowed_for = []

    def refresh_settings(self, config):
        pass

    @contextmanager
    def borrow_proxy(self, url, **kwargs):
        self.borrowed_for.append(url)
        yield self.proxy


def make_downloader(answers, media_request_headers=None, processor=VideoDownloaderPlus):
    """
    A video downloader that gets the given answers, in order, for the links it requests

    What it asks for the links with is kept as `request_options`. yt-dlp
    downloads borrow their proxy from `downloader.manager.proxy_delegator`, a
    `FakeProxyPool`.

    :param processor:  The video downloader to make, e.g. one for a single platform
    """
    downloader = processor.__new__(processor)
    downloader.manager = SimpleNamespace(proxy_delegator=FakeProxyPool())
    downloader.source_dataset = FakeSource([], media_request_headers)
    downloader.dataset = MagicMock()
    downloader.config = MagicMock()
    downloader.config.get.side_effect = lambda key, default=None, **kwargs: default
    downloader.interrupted = False
    downloader.downloaded_videos = 0
    downloader.total_possible_videos = len(answers)
    downloader.warning_message = None
    downloader.flush_proxied_requests = MagicMock()
    downloader.staging_filenames = UniqueFilenames()

    def iterate_proxied_requests(urls, **kwargs):
        downloader.request_options = kwargs
        return zip(urls, answers)

    downloader.iterate_proxied_requests = iterate_proxied_requests
    return downloader


def download_directly(answers, tmp_path, domains=None, also_indirect="none", ignore_not_video=False,
                      media_request_headers=None):
    """
    Run the direct download step

    :param list answers:  One website answer per link
    :param list domains:  Website of each link; all links are on the same website if not given
    :param dict media_request_headers:  Extra headers the dataset's data source asks for
    :return tuple:  The downloader, the step's results, and what was noted per link
    """
    domains = domains or ["video.example.com"] * len(answers)
    urls = [f"https://{domain}/{number}.mp4" for number, domain in enumerate(domains)]
    urls_dict = {url: {"success": False, "retry": True} for url in urls}
    downloader = make_downloader(answers, media_request_headers)
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


def test_direct_downloads_send_the_data_sources_headers(tmp_path):
    # Weibo's video servers refuse a browser that does not say it came from Weibo
    downloader, _, _ = download_directly([VIDEO], tmp_path, media_request_headers={"Referer": "https://weibo.com/"})

    assert downloader.request_options["headers"] == {
        "User-Agent": VideoDownloaderPlus.DIRECT_DOWNLOAD_UA,
        "Referer": "https://weibo.com/",
    }


def test_direct_downloads_send_only_a_user_agent_by_default(tmp_path):
    downloader, _, _ = download_directly([VIDEO], tmp_path)

    assert downloader.request_options["headers"] == {"User-Agent": VideoDownloaderPlus.DIRECT_DOWNLOAD_UA}


def test_ignoring_non_videos_does_not_stop(tmp_path):
    _, results, _ = download_directly([WEB_PAGE] * 15, tmp_path, ignore_not_video=True)

    assert not results["stop_processing"]
    assert results["processed"] == 15


# --- yt-dlp downloads --------------------------------------------------------------

SITE_ERROR = {"success": False, "site_error": True}
SETTINGS_ERROR = {"success": False, "site_error": False}
DOWNLOADED = {"success": True, "site_error": False}


def download_with_ytdlp(outcomes, tmp_path, in_preset=False, processor=VideoDownloaderPlus):
    """
    Run the yt-dlp download step

    :param list outcomes:  What downloading each link with yt-dlp results in
    :param bool in_preset:  Whether the downloader runs as part of a preset, e.g. for Weibo
    :param processor:  The video downloader to run, e.g. one for a single platform
    :return tuple:  The downloader and the step's results
    """
    urls = [f"https://www.youtube.com/watch?v={number}" for number in range(len(outcomes))]
    urls_dict = {url: {"success": False, "retry": True} for url in urls}
    downloader = make_downloader([], processor=processor)
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
    # the Weibo preset turns yt-dlp on itself; users cannot change that
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


def test_no_usable_proxy_stops_the_yt_dlp_downloads(tmp_path):
    # this would be the same for every following link
    no_proxy = NoProxiesAvailableError("No proxy can be used for https://www.youtube.com/watch?v=0")
    downloader, results = download_with_ytdlp([no_proxy, DOWNLOADED, DOWNLOADED], tmp_path)

    assert downloader._download_single_ytdlp.call_count == 1
    assert results["processed"] == 0
    assert "no proxy" in downloader.warning_message


# --- proxies for yt-dlp ------------------------------------------------------------

class RecordingYoutubeDL:
    """
    yt-dlp, downloading a video without making requests

    The options of every YoutubeDL that is made are kept in `made`. If
    `already_downloaded` is set, the first download finds that the video was
    downloaded before, as for a second link to the same video.
    """
    made = []
    already_downloaded = False

    def __init__(self, options):
        self.options = options
        RecordingYoutubeDL.made.append(options)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def extract_info(self, url, download=True):
        info = {"_filename": "/staging/video.mp4", "extractor": "TikTok", "id": "1"}
        if not download:
            return info
        if RecordingYoutubeDL.already_downloaded:
            raise ExistingVideoReached()
        for hook in self.options.get("progress_hooks", []):
            hook({"status": "finished"})
        for hook in self.options.get("postprocessor_hooks", []):
            hook({"status": "finished", "info_dict": info})


def download_post_with_ytdlp(proxy, monkeypatch, already_downloaded=False):
    """
    Download one post with yt-dlp, through the given borrowed proxy

    :return tuple:  The options of each YoutubeDL that was made, and what was noted for the post
    """
    monkeypatch.setattr(RecordingYoutubeDL, "made", [])
    monkeypatch.setattr(RecordingYoutubeDL, "already_downloaded", already_downloaded)
    monkeypatch.setattr(download_videos.yt_dlp, "YoutubeDL", RecordingYoutubeDL)
    downloader = make_downloader([])
    downloader.manager.proxy_delegator.proxy = proxy
    downloader.videos_downloaded_from_url = set()
    downloader.yt_dlp_archive_map = {}
    url = "https://www.tiktok.com/@user/video/1"
    urls_dict = {url: {}}
    ydl_opts = {"postprocessor_hooks": [downloader.yt_dlp_post_monitor],
                "progress_hooks": [downloader.yt_dlp_monitor]}

    result = downloader._download_single_ytdlp(url, ydl_opts, urls_dict)

    assert downloader.manager.proxy_delegator.borrowed_for == [url]
    assert "proxy" not in ydl_opts  # the options of the next link are left alone
    return result, RecordingYoutubeDL.made, urls_dict[url]


def test_yt_dlp_downloads_through_the_borrowed_proxy(monkeypatch):
    result, made, url_info = download_post_with_ytdlp("http://user:secret@10.0.0.1:3128", monkeypatch)

    assert result["success"]
    assert made[0]["proxy"] == "http://user:secret@10.0.0.1:3128"
    # as for direct downloads, the proxy is noted without its username and password
    assert url_info["files"][0]["metadata"]["proxy"] == "http://10.0.0.1:3128"


def test_yt_dlp_downloads_without_a_proxy_when_connecting_directly(monkeypatch):
    result, made, url_info = download_post_with_ytdlp(DelegatedRequestHandler.PROXY_LOCALHOST, monkeypatch)

    assert result["success"]
    assert "proxy" not in made[0]
    assert url_info["files"][0]["metadata"]["proxy"] == DelegatedRequestHandler.PROXY_LOCALHOST


def test_looking_up_an_already_downloaded_video_uses_the_same_proxy(monkeypatch):
    _, made, _ = download_post_with_ytdlp("http://10.0.0.1:3128", monkeypatch, already_downloaded=True)

    assert len(made) == 2
    assert made[1]["proxy"] == "http://10.0.0.1:3128"


# --- which links are collected -----------------------------------------------------

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
    """Where every post has a video, yt-dlp can find it on the page of a post without a video link"""
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


# --- TikTok ------------------------------------------------------------------------

TIKTOK_VIDEO_POST = {"id": "7600000000000000001", "is_image_post": "no",
                     "tiktok_url": "https://www.tiktok.com/@example/video/7600000000000000001"}
# the link of an image post looks like a video's; only `is_image_post` tells them apart
TIKTOK_IMAGE_POST = {"id": "7600000000000000002", "is_image_post": "yes",
                     "tiktok_url": "https://www.tiktok.com/@example/video/7600000000000000002"}


def collect_tiktok_links(items, parameters=None):
    """
    Collect the links the TikTok downloader would try

    :return tuple:  Video links, and post URLs that only yt-dlp is asked about
    """
    downloader = make_downloader([], processor=TikTokVideoDownloader)
    downloader.source_dataset = FakeSource(items)
    downloader.parameters = parameters or {}
    return downloader.collect_video_urls()


def test_tiktok_posts_go_straight_to_yt_dlp():
    # TikTok's own video links soon stop working, so none are tried as video files first
    urls, yt_dlp_only = collect_tiktok_links([TIKTOK_VIDEO_POST, TIKTOK_IMAGE_POST])

    assert urls == {}
    assert yt_dlp_only == {TIKTOK_VIDEO_POST["tiktok_url"]: {"post_ids": {TIKTOK_VIDEO_POST["id"]}}}


def test_tiktok_photo_links_are_left_out():
    photo_post = {"id": "3", "tiktok_url": "https://www.tiktok.com/@example/photo/3"}

    _, yt_dlp_only = collect_tiktok_links([TIKTOK_VIDEO_POST, photo_post])

    assert list(yt_dlp_only) == [TIKTOK_VIDEO_POST["tiktok_url"]]


def test_uploaded_tiktok_posts_use_the_chosen_column():
    post = {"id": "4", "post_link": "https://www.tiktok.com/@example/video/4"}

    _, yt_dlp_only = collect_tiktok_links([post], {"url_column": "post_link"})

    assert list(yt_dlp_only) == [post["post_link"]]


def test_tiktok_dataset_of_only_image_posts_says_so():
    with pytest.raises(ProcessorException, match="image posts"):
        collect_tiktok_links([TIKTOK_IMAGE_POST])


def test_tiktok_downloader_always_uses_yt_dlp(monkeypatch):
    monkeypatch.setattr(VideoDownloaderPlus, "process", lambda self: None)
    downloader = TikTokVideoDownloader.__new__(TikTokVideoDownloader)
    downloader.parameters = {"amount": 10}

    downloader.process()

    assert downloader.parameters["also_indirect"] == "all"


def test_tiktok_downloader_does_not_suggest_changing_the_non_direct_setting(tmp_path):
    # TikTok users are not offered that setting
    downloader, results = download_with_ytdlp([SITE_ERROR] * 5, tmp_path, processor=TikTokVideoDownloader)

    assert results["processed"] == 5
    assert "non-direct" not in downloader.warning_message
    assert "working links" in downloader.warning_message


# what yt-dlp fails with, as the downloader records it
REFUSED_VIDEO_FILE = "DownloadError: ERROR: unable to download video data: HTTP Error 403: Forbidden"
REFUSED_PAGE = "DownloadError: ERROR: [TikTok] 1: Unable to download webpage: HTTP Error 403: Forbidden"
NEEDS_LOGIN = "DownloadError: ERROR: [TikTok] 1: This post may not be comfortable for some audiences. Log in for access."


def download_tiktok_post(errors, monkeypatch):
    """
    Download one TikTok post with yt-dlp

    :param list errors:  What each yt-dlp attempt fails with, in order; None for a successful download
    :return tuple:  The downloader, the result, the number of attempts, and what was noted for the post
    """
    url = TIKTOK_VIDEO_POST["tiktok_url"]
    attempts = []

    def attempt(self, url, ydl_opts, urls_dict):
        error = errors[len(attempts)]
        attempts.append(error)
        if error is None:
            return {"success": True, "site_error": False}
        urls_dict[url]["error"] = error
        return {"success": False, "site_error": True}

    monkeypatch.setattr(VideoDownloaderPlus, "_download_single_ytdlp", attempt)
    downloader = make_downloader([], processor=TikTokVideoDownloader)
    urls_dict = {url: {}}
    result = downloader._download_single_ytdlp(url, {}, urls_dict)
    return downloader, result, len(attempts), urls_dict[url]


def test_tiktok_refused_video_file_is_tried_once_more(monkeypatch):
    # TikTok sometimes sends a post's page without the cookie its video servers ask for
    downloader, result, attempts, url_info = download_tiktok_post([REFUSED_VIDEO_FILE, None], monkeypatch)

    assert result["success"]
    assert attempts == 2
    assert "error" not in url_info
    assert "trying once more" in downloader.dataset.log.call_args.args[0]


def test_tiktok_refused_video_file_is_tried_only_once_more(monkeypatch):
    _, result, attempts, url_info = download_tiktok_post([REFUSED_VIDEO_FILE] * 3, monkeypatch)

    assert not result["success"]
    assert attempts == 2
    assert url_info["error"] == REFUSED_VIDEO_FILE


@pytest.mark.parametrize("error", [REFUSED_PAGE, NEEDS_LOGIN])
def test_other_tiktok_errors_are_not_tried_again(error, monkeypatch):
    _, result, attempts, _ = download_tiktok_post([error, None], monkeypatch)

    assert not result["success"]
    assert attempts == 1


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


def test_tiktok_datasets_get_the_tiktok_downloader():
    tiktok = FakeDataset("tiktok-search")

    assert TikTokVideoDownloader.is_compatible_with(tiktok, config=MagicMock())
    assert not VideoDownloaderPlus.is_compatible_with(tiktok, config=MagicMock())
