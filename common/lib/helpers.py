"""
Miscellaneous helper functions for the 4CAT backend
"""
import subprocess
import imagehash
import hashlib
import requests
import datetime
import smtplib
import fnmatch
import socket
import oslex
import copy
import time
import json
import math
import ural
import csv
import ssl
import re
import os
import io

from pathlib import Path
from collections.abc import MutableMapping
from html.parser import HTMLParser
from urllib.parse import urlparse, urlunparse
from calendar import monthrange
from packaging import version
from PIL import Image

from common.config_manager import CoreConfigManager
from common.lib.user_input import UserInput
__all__ = ("UserInput",)

core_config = CoreConfigManager()

def init_datasource(database, logger, queue, name, config):
    """
    Initialize data source

    Queues jobs to scrape the boards that were configured to be scraped in the
    4CAT configuration file. If none were configured, nothing happens.

    :param Database database:  Database connection instance
    :param Logger logger:  Log handler
    :param JobQueue queue:  Job Queue instance
    :param string name:  ID of datasource that is being initialised
    :param config:  Configuration reader
    """
    pass

def get_datasource_example_keys(db, modules, dataset_type):
    """
    Get example keys for a datasource
    """
    from common.lib.dataset import DataSet
    example_dataset_key = db.fetchone("SELECT key from datasets WHERE type = %s and is_finished = True and num_rows > 0 ORDER BY timestamp_finished DESC LIMIT 1", (dataset_type,))
    if example_dataset_key:
        example_dataset = DataSet(db=db, key=example_dataset_key["key"], modules=modules)
        return example_dataset.get_columns()
    return []

def strip_tags(html, convert_newlines=True):
    """
    Strip HTML from a string

    :param html: HTML to strip
    :param convert_newlines: Convert <br> and </p> tags to \n before stripping
    :return: Stripped HTML
    """
    if not html:
        return ""

    deduplicate_newlines = re.compile(r"\n+")

    if convert_newlines:
        html = html.replace("<br>", "\n").replace("</p>", "</p>\n")
        html = deduplicate_newlines.sub("\n", html)

    class HTMLStripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.reset()
            self.strict = False
            self.convert_charrefs = True
            self.fed = []

        def handle_data(self, data):
            self.fed.append(data)

        def get_data(self):
            return "".join(self.fed)

    stripper = HTMLStripper()
    stripper.feed(html)
    return stripper.get_data()


def sniff_encoding(file):
    """
    Determine encoding from raw file bytes

    Currently only distinguishes UTF-8 and UTF-8 with BOM

    :param file:
    :return:
    """
    if type(file) is bytearray:
        maybe_bom = file[:3]
    elif hasattr(file, "getbuffer"):
        buffer = file.getbuffer()
        maybe_bom = buffer[:3].tobytes()
    elif hasattr(file, "peek"):
        buffer = file.peek(32)
        maybe_bom = buffer[:3]
    else:
        maybe_bom = False

    return "utf-8-sig" if maybe_bom == b"\xef\xbb\xbf" else "utf-8"

def sniff_csv_dialect(csv_input):
    """
    Determine CSV dialect for an input stream

    :param csv_input:  Input stream
    :return tuple:  Tuple: Dialect object and a boolean representing whether
    the CSV file seems to have a header
    """
    encoding = sniff_encoding(csv_input)
    if type(csv_input) is io.TextIOWrapper:
        wrapped_input = csv_input
    else:
        wrapped_input = io.TextIOWrapper(csv_input, encoding=encoding)
    wrapped_input.seek(0)
    sample = wrapped_input.read(1024 * 1024)
    wrapped_input.seek(0)
    has_header = csv.Sniffer().has_header(sample)
    dialect = csv.Sniffer().sniff(sample, delimiters=(",", ";", "\t"))

    return dialect, has_header


def get_git_branch():
    """
    Get current git branch

    If the 4CAT root folder is a git repository, this function will return the
    name of the currently checked-out branch. If the folder is not a git
    repository or git is not installed an empty string is returned.
    """
    try:
        root_dir = str(core_config.get('PATH_ROOT').resolve())
        branch = subprocess.run(oslex.split(f"git -C {oslex.quote(root_dir)} branch --show-current"), stdout=subprocess.PIPE)
        if branch.returncode != 0:
            raise ValueError()
        branch_name = branch.stdout.decode("utf-8").strip()
        if not branch_name:
            # Check for detached HEAD state
            # Most likely occuring because of checking out release tags (which are not branches) or commits
            head_status = subprocess.run(oslex.split(f"git -C {oslex.quote(root_dir)} status"), stdout=subprocess.PIPE)
            if head_status.returncode == 0:
                for line in head_status.stdout.decode("utf-8").split("\n"):
                    if any([detached_message in line for detached_message in ("HEAD detached from", "HEAD detached at")]):
                        branch_name = line.split("/")[-1] if "/" in line else line.split(" ")[-1]
                        return branch_name.strip()
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        return ""


def get_software_commit(worker=None):
    """
    Get current 4CAT git commit hash

    Use `get_software_version()` instead if you need the release version
    number rather than the precise commit hash.

    If no version file is available, run `git show` to test if there is a git
    repository in the 4CAT root folder, and if so, what commit is currently
    checked out in it.

    For extensions, get the repository information for that extension, or if
    the extension is not a git repository, return empty data.

    :param BasicWorker processor:  Worker to get commit for. If not given, get
    version information for the main 4CAT installation.

    :return tuple:  4CAT git commit hash, repository name
    """
    # try git command line within the 4CAT root folder
    # if it is a checked-out git repository, it will tell us the hash of
    # the currently checked-out commit

    # path has no Path.relative()...
    try:
        # if extension, go to the extension file's path
        # we will run git here - if it is not its own repository, we have no
        # useful version info (since the extension is by definition not in the
        # main 4CAT repository) and will return an empty value
        if worker and worker.is_extension:
            relative_filepath = Path(re.sub(r"^[/\\]+", "", worker.filepath)).parent
            working_dir = str(core_config.get("PATH_ROOT").joinpath(relative_filepath).resolve())
            # check if we are in the extensions' own repo or 4CAT's
            git_cmd = f"git -C {oslex.quote(working_dir)} rev-parse --show-toplevel"
            repo_level = subprocess.run(oslex.split(git_cmd), stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            if Path(repo_level.stdout.decode("utf-8")) == core_config.get("PATH_ROOT"):
                # not its own repository
                return ("", "")

        else:
            working_dir = str(core_config.get("PATH_ROOT").resolve())

        show = subprocess.run(oslex.split(f"git -C {oslex.quote(working_dir)} show"), stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        if show.returncode != 0:
            raise ValueError()
        commit = show.stdout.decode("utf-8").split("\n")[0].split(" ")[1]

        # now get the repository the commit belongs to, if we can
        origin = subprocess.run(oslex.split(f"git -C {oslex.quote(working_dir)} config --get remote.origin.url"), stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        if origin.returncode != 0 or not origin.stdout:
            raise ValueError()
        repository = origin.stdout.decode("utf-8").strip()
        if repository.endswith(".git"):
            repository = repository[:-4]

    except (subprocess.SubprocessError, IndexError, TypeError, ValueError, FileNotFoundError):
        return ("", "")

    return (commit, repository)

def get_software_version():
    """
    Get current 4CAT version

    This is the actual software version, i.e. not the commit hash (see
    `get_software_hash()` for that). The current version is stored in a file
    with a canonical location: if the file doesn't exist, an empty string is
    returned.

    :return str:  Software version, for example `1.37`.
    """
    current_version_file = core_config.get("PATH_CONFIG").joinpath(".current-version")
    if not current_version_file.exists():
        return ""

    with current_version_file.open() as infile:
        return infile.readline().strip()

def get_github_version(repo_url, timeout=5):
    """
    Get latest release tag version from GitHub

    Will raise a ValueError if it cannot retrieve information from GitHub.

    :param str repo_url:  GitHub repository URL
    :param int timeout:  Timeout in seconds for HTTP request

    :return tuple:  Version, e.g. `1.26`, and release URL.
    """
    if not repo_url.endswith("/"):
        repo_url += "/"

    repo_id = re.sub(r"(\.git)?/?$", "", re.sub(r"^https?://(www\.)?github\.com/", "", repo_url))

    api_url = "https://api.github.com/repos/%s/releases/latest" % repo_id
    response = requests.get(api_url, timeout=timeout)
    response = response.json()
    if response.get("message") == "Not Found":
        raise ValueError("Invalid GitHub URL or repository name")

    latest_tag = response.get("tag_name", "unknown")
    if latest_tag.startswith("v"):
        latest_tag = re.sub(r"^v", "", latest_tag)

    return (latest_tag, response.get("html_url"))

def get_ffmpeg_version(ffmpeg_path):
    """
    Determine ffmpeg version

    This can be necessary when using commands that change name between versions.

    :param ffmpeg_path: ffmpeg executable path
    :return packaging.version:  Comparable ersion
    """
    command = [ffmpeg_path, "-version"]
    ffmpeg_version = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE)

    ffmpeg_version = ffmpeg_version.stdout.decode("utf-8").split("\n")[0].strip().split(" version ")[1]
    ffmpeg_version = re.split(r"[^0-9.]", ffmpeg_version)[0]

    return version.parse(ffmpeg_version)


def find_extensions():
    """
    Find 4CAT extensions and load their metadata

    Looks for subfolders of the extension folder, and loads additional metadata
    where available.

    :return tuple:  A tuple with two items; the extensions, as an ID -> metadata
    dictionary, and a list of (str) errors encountered while loading
    """
    extension_path = core_config.get("PATH_EXTENSIONS")
    errors = []
    if not extension_path.exists() or not extension_path.is_dir():
        return {}, errors

    # each folder in the extensions folder is an extension
    extensions = {
        extension.name: {
            "name": extension.name,
            "version": "",
            "url": "",
            "git_url": "",
            "is_git": False,
        } for extension in sorted(os.scandir(extension_path), key=lambda x: x.name) if extension.is_dir() and not extension.name.startswith("__")
    }

    # collect metadata for extensions
    allowed_metadata_keys = ("name", "version", "url")
    for extension in extensions:
        extension_folder = extension_path.joinpath(extension)
        metadata_file = extension_folder.joinpath("metadata.json")
        if metadata_file.exists():
            with metadata_file.open() as infile:
                try:
                    metadata = json.load(infile)
                    extensions[extension].update({k: metadata[k] for k in metadata if k in allowed_metadata_keys})
                except (TypeError, ValueError) as e:
                    errors.append(f"Error reading metadata file for extension '{extension}' ({e})")
                    continue

        extensions[extension]["is_git"] = extension_folder.joinpath(".git/HEAD").exists()
        if extensions[extension]["is_git"]:
            # try to get remote URL
            try:
                extension_root = str(extension_folder.resolve())
                origin = subprocess.run(oslex.split(f"git -C {oslex.quote(extension_root)} config --get remote.origin.url"), stderr=subprocess.PIPE,
                                        stdout=subprocess.PIPE)
                if origin.returncode != 0 or not origin.stdout:
                    raise ValueError()
                repository = origin.stdout.decode("utf-8").strip()
                if repository.endswith(".git") and "github.com" in repository:
                    # use repo URL
                    repository = repository[:-4]
                extensions[extension]["git_url"] = repository
            except (subprocess.SubprocessError, IndexError, TypeError, ValueError, FileNotFoundError) as e:
                print(e)
                pass

    return extensions, errors


def convert_to_int(value, default=0):
    """
    Convert a value to an integer, with a fallback

    The fallback is used if an Error is thrown during converstion to int.
    This is a convenience function, but beats putting try-catches everywhere
    we're using user input as an integer.

    :param value:  Value to convert
    :param int default:  Default value, if conversion not possible
    :return int:  Converted value
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default

def convert_to_float(value, default=0, force=False) -> float:
    """
    Convert a value to a floating point, with a fallback

    The fallback is used if an Error is thrown during converstion to float.
    This is a convenience function, but beats putting try-catches everywhere
    we're using user input as a floating point number.

    :param value:  Value to convert
    :param int default:  Default value, if conversion not possible
    :param force:   Whether to force the value into a float if it is not empty or None.
    :return float:  Converted value
    """
    if force:
        return float(value) if value else default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def timify(number, short=False):
    """
    Make a number look like an indication of time

    :param number:  Number to convert. If the number is larger than the current
    UNIX timestamp, decrease by that amount
    :return str: A nice, string, for example `1 month, 3 weeks, 4 hours and 2 minutes`
    """
    number = int(number)

    components = []
    if number > time.time():
        number = time.time() - number

    month_length = 30.42 * 86400
    months = math.floor(number / month_length)
    if months:
        components.append(f"{months}{'mt' if short else ' month'}{'s' if months != 1 and not short else ''}")
        number -= (months * month_length)

    week_length = 7 * 86400
    weeks = math.floor(number / week_length)
    if weeks:
        components.append(f"{weeks}{'w' if short else ' week'}{'s' if weeks != 1 and not short else ''}")
        number -= (weeks * week_length)

    day_length = 86400
    days = math.floor(number / day_length)
    if days:
        components.append(f"{days}{'d' if short else ' day'}{'s' if days != 1 and not short else ''}")
        number -= (days * day_length)

    hour_length = 3600
    hours = math.floor(number / hour_length)
    if hours:
        components.append(f"{hours}{'h' if short else ' hour'}{'s' if hours != 1 and not short else ''}")
        number -= (hours * hour_length)

    minute_length = 60
    minutes = math.floor(number / minute_length)
    if minutes:
        components.append(f"{minutes}{'m' if short else ' minute'}{'s' if minutes != 1 and not short else ''}")

    if not components:
        components.append("less than a minute")

    last_str = components.pop()
    time_str = ""
    if components:
        time_str = ", ".join(components)
        time_str += " and "

    return time_str + last_str

def nthify(integer: int) -> str:
    """
    Takes an integer and returns a string with 'st', 'nd', 'rd', or 'th' as suffix, depending on the number.
    """
    int_str = str(integer).strip()
    if int_str.endswith("1"):
        suffix = "st"
    elif int_str.endswith("2"):
        suffix = "nd"
    elif int_str.endswith("3"):
        suffix = "rd"
    else:
        suffix = "th"
    return int_str + suffix

def andify(items):
    """
    Format a list of items for use in text

    Returns a comma-separated list, the last item preceded by "and"

    :param items:  Iterable list
    :return str:  Formatted string
    """

    items = items.copy()

    if len(items) == 0:
        return ""
    elif len(items) == 1:
        return str(items[0])

    result = f" and {items.pop()}"
    return ", ".join([str(item) for item in items]) + result

def ellipsiate(text, length, inside=False, ellipsis_str="&hellip;"):
    if len(text) <= length:
        return text

    elif not inside:
        return text[:length] + ellipsis_str

    else:
        # two cases: URLs and normal text
        # for URLs, try to only ellipsiate after the domain name
        # this makes the URLs easier to read when shortened
        if ural.is_url(text):
            pre_part = "/".join(text.split("/")[:3])
            if len(pre_part) < length - 6:  # kind of arbitrary
                before = len(pre_part) + 1
            else:
                before = math.floor(length / 2)
        else:
            before = math.floor(length / 2)

        after = len(text) - before
        return text[:before] + ellipsis_str + text[after:]

def hash_file(image_file, hash_type="file-hash"):
    """
    Generate an image hash

    :param Path image_file:  Image file to hash
    :param str hash_type:  Hash type, one of `file-hash`, `colorhash`,
    `phash`, `average_hash`, `dhash`
    :return str:  Hexadecimal hash value
    """
    if not image_file.exists():
        raise FileNotFoundError()

    if hash_type == "file-hash":
        hasher = hashlib.sha1()

        # Open the file in binary mode
        with image_file.open("rb") as infile:
            # Read and update hash in chunks to handle large files
            while chunk := infile.read(1024):
                hasher.update(chunk)

        return hasher.hexdigest()

    elif hash_type in ("colorhash", "phash", "average_hash", "dhash"):
        image = Image.open(image_file)

        return str(getattr(imagehash, hash_type)(image))

    else:
        raise NotImplementedError(f"Unknown hash type '{hash_type}'")

def get_yt_compatible_ids(yt_ids):
    """
    :param yt_ids list, a list of strings
    :returns list, a ist of joined strings in pairs of 50

    Takes a list of IDs and returns list of joined strings
    in pairs of fifty. This should be done for the YouTube API
    that requires a comma-separated string and can only return
    max fifty results.
    """

    # If there's only one item, return a single list item
    if isinstance(yt_ids, str):
        return [yt_ids]

    ids = []
    last_i = 0
    for i, yt_id in enumerate(yt_ids):

        # Add a joined string per fifty videos
        if i % 50 == 0 and i != 0:
            ids_string = ",".join(yt_ids[last_i:i])
            ids.append(ids_string)
            last_i = i

        # If the end of the list is reached, add the last data
        elif i == (len(yt_ids) - 1):
            ids_string = ",".join(yt_ids[last_i:i])
            ids.append(ids_string)

    return ids


def get_4cat_canvas(path, width, height, header=None, footer="made with 4CAT", fontsize_normal=None,
                    fontsize_small=None, fontsize_large=None):
    """
    Get a standard SVG canvas to draw 4CAT graphs to

    Adds a border, footer, header, and some basic text styling

    :param path:  The path where the SVG graph will be saved
    :param width:  Width of the canvas
    :param height:  Height of the canvas
    :param header:  Header, if necessary to draw
    :param footer:  Footer text, if necessary to draw. Defaults to shameless
    4CAT advertisement.
    :param fontsize_normal:  Font size of normal text
    :param fontsize_small:  Font size of small text (e.g. footer)
    :param fontsize_large:  Font size of large text (e.g. header)
    :return SVG:  SVG canvas (via svgwrite) that can be drawn to
    """
    from svgwrite.container import SVG, Hyperlink
    from svgwrite.drawing import Drawing
    from svgwrite.shapes import Rect
    from svgwrite.text import Text

    if fontsize_normal is None:
        fontsize_normal = width / 75

    if fontsize_small is None:
        fontsize_small = width / 100

    if fontsize_large is None:
        fontsize_large = width / 50

    # instantiate with border and white background
    canvas = Drawing(str(path), size=(width, height), style="font-family:monospace;font-size:%ipx" % fontsize_normal)
    canvas.add(Rect(insert=(0, 0), size=(width, height), stroke="#000", stroke_width=2, fill="#FFF"))

    # header
    if header:
        header_shape = SVG(insert=(0, 0), size=("100%", fontsize_large * 2))
        header_shape.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
        header_shape.add(
            Text(insert=("50%", "50%"), text=header, dominant_baseline="middle", text_anchor="middle", fill="#FFF",
                 style="font-size:%ipx" % fontsize_large))
        canvas.add(header_shape)

    # footer (i.e. 4cat banner)
    if footer:
        footersize = (fontsize_small * len(footer) * 0.7, fontsize_small * 2)
        footer_shape = SVG(insert=(width - footersize[0], height - footersize[1]), size=footersize)
        footer_shape.add(Rect(insert=(0, 0), size=("100%", "100%"), fill="#000"))
        link = Hyperlink(href="https://4cat.nl")
        link.add(
            Text(insert=("50%", "50%"), text=footer, dominant_baseline="middle", text_anchor="middle", fill="#FFF",
                 style="font-size:%ipx" % fontsize_small))
        footer_shape.add(link)
        canvas.add(footer_shape)

    return canvas


def call_api(action, payload=None, wait_for_response=True):
    """
    Send message to server

    Calls the internal API and returns interpreted response. "status" is always 
    None if wait_for_response is False.

    :param str action: API action
    :param payload: API payload
    :param bool wait_for_response:  Wait for response? If not close connection
    immediately after sending data.

    :return: API response {"status": "success"|"error", "response": response, "error": error}
    """
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(15)
    config = CoreConfigManager()
    try:
        connection.connect((config.get('API_HOST'), config.get('API_PORT')))
    except ConnectionRefusedError:
        return {"status": "error", "error": "Connection refused"}

    msg = json.dumps({"request": action, "payload": payload})
    connection.sendall(msg.encode("ascii", "ignore"))

    response_data = {
        "status": None,
        "response": None,
        "error": None
    }

    if wait_for_response:
        try:
            response = ""
            while True:
                bytes = connection.recv(2048)
                if not bytes:
                    break

                response += bytes.decode("ascii", "ignore")
        except (socket.timeout, TimeoutError):
            response_data["status"] = "error"
            response_data["error"] = "Connection timed out"

    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        # already shut down automatically
        pass
    connection.close()

    if wait_for_response and response:
        try:
            json_response = json.loads(response)
            response_data["response"] = json_response["response"]
            response_data["error"] = json_response.get("error", None)
            response_data["status"] = "error" if json_response.get("error") else "success"
        except json.JSONDecodeError:
            response_data["status"] = "error"
            response_data["error"] = "Invalid JSON response"
            response_data["response"] = response
    
    return response_data

def get_interval_descriptor(item, interval, item_column="timestamp"):
    """
    Get interval descriptor based on timestamp

    :param dict item:  Item to generate descriptor for, should have a
    "timestamp" key
    :param str interval:  Interval, one of "all", "overall", "year",
    "month", "week", "day"
    :param str item_column:  Column name in the item dictionary that contains
    the timestamp. Defaults to "timestamp".
    :return str:  Interval descriptor, e.g. "overall", "unknown_date", "2020", "2020-08",
    "2020-43", "2020-08-01"
    """
    if interval in ("all", "overall"):
        return interval
    
    if not item.get(item_column, None):
        return "unknown_date"

    # Catch cases where a custom timestamp has an epoch integer as value.
    try:
        timestamp = int(item[item_column])
        try:
            timestamp = datetime.datetime.fromtimestamp(timestamp)
        except (ValueError, TypeError):
            raise ValueError("Invalid timestamp '%s'" % str(item["timestamp"]))
    except (TypeError, ValueError):
        try:
            timestamp = datetime.datetime.strptime(item["timestamp"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            raise ValueError("Invalid date '%s'" % str(item["timestamp"]))

    if interval == "year":
        return str(timestamp.year)
    elif interval == "month":
        return str(timestamp.year) + "-" + str(timestamp.month).zfill(2)
    elif interval == "week":
        return str(timestamp.isocalendar()[0]) + "-" + str(timestamp.isocalendar()[1]).zfill(2)
    elif interval == "hour":
        return str(timestamp.year) + "-" + str(timestamp.month).zfill(2) + "-" + str(timestamp.day).zfill(
            2) + " " + str(timestamp.hour).zfill(2)
    elif interval == "minute":
        return str(timestamp.year) + "-" + str(timestamp.month).zfill(2) + "-" + str(timestamp.day).zfill(
            2) + " " + str(timestamp.hour).zfill(2) + ":" + str(timestamp.minute).zfill(2)
    else:
        return str(timestamp.year) + "-" + str(timestamp.month).zfill(2) + "-" + str(timestamp.day).zfill(2)


def pad_interval(intervals, first_interval=None, last_interval=None):
    """
    Pad an interval so all intermediate intervals are filled

    Warning, ugly code (PRs very welcome)

    :param dict intervals:  A dictionary, with dates (YYYY{-MM}{-DD}) as keys
    and a numerical value.
    :param first_interval:
    :param last_interval:
    :return:
    """
    missing = 0
    try:
        test_key = list(intervals.keys())[0]
    except IndexError:
        return 0, {}

    # first determine the boundaries of the interval
    # these may be passed as parameters, or they can be inferred from the
    # interval given
    if first_interval:
        first_interval = str(first_interval)
        first_year = int(first_interval[0:4])
        if len(first_interval) > 4:
            first_month = int(first_interval[5:7])
        if len(first_interval) > 7:
            first_day = int(first_interval[8:10])
        if len(first_interval) > 10:
            first_hour = int(first_interval[11:13])
        if len(first_interval) > 13:
            first_minute = int(first_interval[14:16])

    else:
        first_year = min([int(i[0:4]) for i in intervals])
        if len(test_key) > 4:
            first_month = min([int(i[5:7]) for i in intervals if int(i[0:4]) == first_year])
        if len(test_key) > 7:
            first_day = min(
                [int(i[8:10]) for i in intervals if int(i[0:4]) == first_year and int(i[5:7]) == first_month])
        if len(test_key) > 10:
            first_hour = min(
                [int(i[11:13]) for i in intervals if
                 int(i[0:4]) == first_year and int(i[5:7]) == first_month and int(i[8:10]) == first_day])
        if len(test_key) > 13:
            first_minute = min(
                [int(i[14:16]) for i in intervals if
                 int(i[0:4]) == first_year and int(i[5:7]) == first_month and int(i[8:10]) == first_day and int(
                     i[11:13]) == first_hour])

    if last_interval:
        last_interval = str(last_interval)
        last_year = int(last_interval[0:4])
        if len(last_interval) > 4:
            last_month = int(last_interval[5:7])
        if len(last_interval) > 7:
            last_day = int(last_interval[8:10])
        if len(last_interval) > 10:
            last_hour = int(last_interval[11:13])
        if len(last_interval) > 13:
            last_minute = int(last_interval[14:16])
    else:
        last_year = max([int(i[0:4]) for i in intervals])
        if len(test_key) > 4:
            last_month = max([int(i[5:7]) for i in intervals if int(i[0:4]) == last_year])
        if len(test_key) > 7:
            last_day = max(
                [int(i[8:10]) for i in intervals if int(i[0:4]) == last_year and int(i[5:7]) == last_month])
        if len(test_key) > 10:
            last_hour = max(
                [int(i[11:13]) for i in intervals if
                 int(i[0:4]) == last_year and int(i[5:7]) == last_month and int(i[8:10]) == last_day])
        if len(test_key) > 13:
            last_minute = max(
                [int(i[14:16]) for i in intervals if
                 int(i[0:4]) == last_year and int(i[5:7]) == last_month and int(i[8:10]) == last_day and int(
                     i[11:13]) == last_hour])

    has_month = re.match(r"^[0-9]{4}-[0-9]", test_key)
    has_day = re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}", test_key)
    has_hour = re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}", test_key)
    has_minute = re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}", test_key)

    all_intervals = []
    for year in range(first_year, last_year + 1):
        year_interval = str(year)

        if not has_month:
            all_intervals.append(year_interval)
            continue

        start_month = first_month if year == first_year else 1
        end_month = last_month if year == last_year else 12
        for month in range(start_month, end_month + 1):
            month_interval = year_interval + "-" + str(month).zfill(2)

            if not has_day:
                all_intervals.append(month_interval)
                continue

            start_day = first_day if all((year == first_year, month == first_month)) else 1
            end_day = last_day if all((year == last_year, month == last_month)) else monthrange(year, month)[1]
            for day in range(start_day, end_day + 1):
                day_interval = month_interval + "-" + str(day).zfill(2)

                if not has_hour:
                    all_intervals.append(day_interval)
                    continue

                start_hour = first_hour if all((year == first_year, month == first_month, day == first_day)) else 0
                end_hour = last_hour if all((year == last_year, month == last_month, day == last_day)) else 23
                for hour in range(start_hour, end_hour + 1):
                    hour_interval = day_interval + " " + str(hour).zfill(2)

                    if not has_minute:
                        all_intervals.append(hour_interval)
                        continue

                    start_minute = first_minute if all(
                        (year == first_year, month == first_month, day == first_day, hour == first_hour)) else 0
                    end_minute = last_minute if all(
                        (year == last_year, month == last_month, day == last_day, hour == last_hour)) else 59

                    for minute in range(start_minute, end_minute + 1):
                        minute_interval = hour_interval + ":" + str(minute).zfill(2)
                        all_intervals.append(minute_interval)

    for interval in all_intervals:
        if interval not in intervals:
            intervals[interval] = 0
            missing += 1

    # sort while we're at it
    intervals = {key: intervals[key] for key in sorted(intervals)}

    return missing, intervals


def remove_nuls(value):
    """
    Remove \0 from a value

    The CSV library cries about a null byte when it encounters one :( :( :(
    poor little csv cannot handle a tiny little null byte

    So remove them from the data because they should not occur in utf-8 data
    anyway.

    :param value:  Value to remove nulls from. For dictionaries, sets, tuples
    and lists all items are parsed recursively.
    :return value:  Cleaned value
    """
    if type(value) is dict:
        for field in value:
            value[field] = remove_nuls(value[field])
    elif type(value) is list:
        value = [remove_nuls(item) for item in value]
    elif type(value) is tuple:
        value = tuple([remove_nuls(item) for item in value])
    elif type(value) is set:
        value = set([remove_nuls(item) for item in value])
    elif type(value) is str:
        value = value.replace("\0", "")

    return value


class NullAwareTextIOWrapper(io.TextIOWrapper):
    """
    TextIOWrapper that skips null bytes

    This can be used as a file reader that silently discards any null bytes it
    encounters.
    """

    def __next__(self):
        value = super().__next__()
        return remove_nuls(value)


class HashCache:
    """
    Simple cache handler to cache hashed values

    Avoids having to calculate a hash for values that have been hashed before
    """

    def __init__(self, hasher):
        self.hash_cache = {}
        self.hasher = hasher

    def update_cache(self, value):
        """
        Checks the hash_cache to see if the value has been cached previously,
        updates the hash_cache if needed, and returns the hashed value.
        """
        # value = str(value)
        if value not in self.hash_cache:
            author_hasher = self.hasher.copy()
            author_hasher.update(str(value).encode("utf-8"))
            self.hash_cache[value] = author_hasher.hexdigest()
            del author_hasher
        return self.hash_cache[value]


def dict_search_and_update(item, keyword_matches, function):
    """
    Filter fields in an object recursively

    Apply a function to every item and sub item of a dictionary if the key
    contains one of the provided match terms.

    Function loops through a dictionary or list and compares dictionary keys to
    the strings defined by keyword_matches. It then applies the change_function
    to corresponding values.

    Note: if a matching term is found, all nested values will have the function
    applied to them. e.g., all these values would be changed even those with
    not_key_match:

    {'key_match' : 'changed',
    'also_key_match' : {'not_key_match' : 'but_value_still_changed'},
    'another_key_match': ['this_is_changed', 'and_this', {'not_key_match' : 'even_this_is_changed'}]}

    This is a comprehensive (and expensive) approach to updating a dictionary.
    IF a dictionary structure is known, a better solution would be to update
    using specific keys.

    :param Dict/List item:  dictionary/list/json to loop through
    :param String keyword_matches:  list of strings that will be matched to
    dictionary keys. Can contain wildcards which are matched using fnmatch.
    :param Function function:  function appled to all values of any items
    nested under a matching key

    :return Dict/List: Copy of original item, but filtered
    """

    def loop_helper_function(d_or_l, match_terms, change_function):
        """
        Recursive helper function that updates item in place
        """
        if isinstance(d_or_l, dict):
            # Iterate through dictionary
            for key, value in iter(d_or_l.items()):
                if match_terms == 'True' or any([fnmatch.fnmatch(key, match_term) for match_term in match_terms]):
                    # Match found; apply function to all items and sub-items
                    if isinstance(value, (list, dict)):
                        # Pass item through again with match_terms = True
                        loop_helper_function(value, 'True', change_function)
                    elif value is None:
                        pass
                    else:
                        # Update the value
                        d_or_l[key] = change_function(value)
                elif isinstance(value, (list, dict)):
                    # Continue search
                    loop_helper_function(value, match_terms, change_function)
        elif isinstance(d_or_l, list):
            # Iterate through list
            for n, value in enumerate(d_or_l):
                if isinstance(value, (list, dict)):
                    # Continue search
                    loop_helper_function(value, match_terms, change_function)
                elif match_terms == 'True':
                    # List item nested in matching
                    d_or_l[n] = change_function(value)
        else:
            raise Exception('Must pass list or dictionary')

    # Lowercase keyword_matches
    keyword_matches = [keyword.lower() for keyword in keyword_matches]

    # Create deepcopy and return new item
    temp_item = copy.deepcopy(item)
    loop_helper_function(temp_item, keyword_matches, function)
    return temp_item


def get_last_line(filepath):
    """
    Seeks from end of file for '\n' and returns that line

    :param str filepath:  path to file
    :return str: last line of file
    """
    with open(filepath, "rb") as file:
        try:
            # start at the end of file
            file.seek(-2, os.SEEK_END)
            # check if NOT endline i.e. '\n'
            while file.read(1) != b'\n':
                # if not '\n', back up two characters and check again
                file.seek(-2, os.SEEK_CUR)
        except OSError:
            file.seek(0)
        last_line = file.readline().decode()
    return last_line


def add_notification(db, user, notification, expires=None, allow_dismiss=True):
    db.insert("users_notifications", {
        "username": user,
        "notification": notification,
        "timestamp_expires": expires,
        "allow_dismiss": allow_dismiss
    }, safe=True)


def send_email(recipient, message, mail_config):
    """
    Send an e-mail using the configured SMTP settings

    Just a thin wrapper around smtplib, so we don't have to repeat ourselves.
    Exceptions are to be handled outside the function.

    :param list recipient:  Recipient e-mail addresses
    :param MIMEMultipart message:  Message to send
    :param mail_config:  Configuration reader
    """
    # Create a secure SSL context
    context = ssl.create_default_context()

    # Decide which connection type
    with smtplib.SMTP_SSL(mail_config.get('mail.server'), port=mail_config.get('mail.port', 0), context=context) if mail_config.get(
            'mail.ssl') == 'ssl' else smtplib.SMTP(mail_config.get('mail.server'),
                                                   port=mail_config.get('mail.port', 0)) as server:
        if mail_config.get('mail.ssl') == 'tls':
            # smtplib.SMTP adds TLS context here
            server.starttls(context=context)

        # Log in
        if mail_config.get('mail.username') and mail_config.get('mail.password'):
            server.ehlo()
            server.login(mail_config.get('mail.username'), mail_config.get('mail.password'))

        # Send message
        if type(message) is str:
            server.sendmail(mail_config.get('mail.noreply'), recipient, message)
        else:
            server.sendmail(mail_config.get('mail.noreply'), recipient, message.as_string())


def flatten_dict(d: MutableMapping, parent_key: str = '', sep: str = '.'):
    """
    Return a flattened dictionary where nested dictionary objects are given new
    keys using the parent key combined using the seperator with the child key.

    Lists will be converted to json strings via json.dumps()

    :param MutableMapping d:  Dictionary like object
    :param str parent_key: The original parent key prepending future nested keys
    :param str sep: A seperator string used to combine parent and child keys
    :return dict:  A new dictionary with the no nested values
    """

    def _flatten_dict_gen(d, parent_key, sep):
        for k, v in d.items():
            new_key = parent_key + sep + k if parent_key else k
            if isinstance(v, MutableMapping):
                yield from flatten_dict(v, new_key, sep=sep).items()
            elif isinstance(v, (list, set)):
                yield new_key, json.dumps(
                    [flatten_dict(item, new_key, sep=sep) if isinstance(item, MutableMapping) else item for item in v])
            else:
                yield new_key, v

    return dict(_flatten_dict_gen(d, parent_key, sep))


def sets_to_lists(d: MutableMapping):
    """
    Return a dictionary where all nested sets have been converted to lists.

    :param MutableMapping d:  Dictionary like object
    :return dict:  A new dictionary with the no nested sets
    """

    def _check_list(lst):
        return [sets_to_lists(item) if isinstance(item, MutableMapping) else _check_list(item) if isinstance(item, (
        set, list)) else item for item in lst]

    def _sets_to_lists_gen(d):
        for k, v in d.items():
            if isinstance(v, MutableMapping):
                yield k, sets_to_lists(v)
            elif isinstance(v, (list, set)):
                yield k, _check_list(v)
            else:
                yield k, v

    return dict(_sets_to_lists_gen(d))


def url_to_hash(url, remove_scheme=True, remove_www=True):
    """
    Convert a URL to a hash. Allows removing scheme and www prefix before hashing.
    
    :param url: URL to hash
    :param remove_scheme: If True, removes the scheme from URL before hashing
    :param remove_www: If True, removes the www. prefix from URL before hashing
    :return: Hash of the URL
    """
    parsed_url = urlparse(url.lower())
    if parsed_url:
        if remove_scheme:
            parsed_url = parsed_url._replace(scheme="")
        if remove_www:
            netloc = re.sub(r"^www\.", "", parsed_url.netloc)
            parsed_url = parsed_url._replace(netloc=netloc)
        
        # Hash the normalized URL directly
        normalized_url = urlunparse(parsed_url).strip("/")
    else:
        # Unable to parse URL; use regex normalization
        normalized_url = url.lower().strip("/")
        if remove_scheme:
            normalized_url = re.sub(r"^https?://", "", normalized_url)
        if remove_www:
            if not remove_scheme:
                scheme_match = re.match(r"^https?://", normalized_url)
                if scheme_match:
                    scheme = scheme_match.group()
                    temp_url = re.sub(r"^https?://", "", normalized_url)
                    normalized_url = scheme + re.sub(r"^www\.", "", temp_url)
            else:
                normalized_url = re.sub(r"^www\.", "", normalized_url)

    return hashlib.blake2b(normalized_url.encode("utf-8"), digest_size=24).hexdigest()

def url_to_filename(url, staging_area=None, default_name="file", default_ext=".png", max_bytes=255, existing_filenames=None):
        """
        Determine filenames for saved files

        Prefer the original filename (extracted from the URL), but this may not
        always be possible or be an actual filename. Also, avoid using the same
        filename multiple times. Ensures filenames don't exceed max_bytes.

        Check both in-memory existing filenames and on-disk filenames in the
        staging area (if provided) to avoid collisions. Note: With a new staging
        area, only in-memory checks are beneficial; leave as None to skip on-disk checks.

        :param str url:  URLs to determine filenames for
        :param Path staging_area:  Path to the staging area where files are saved
        (to avoid collisions with existing files); if None, no disk checks are done.
        :param str default_name:  Default name to use if no filename can be
        extracted from the URL
        :param str default_ext:  Default extension to use if no filename can be
        extracted from the URL
        :param int max_bytes:  Maximum number of bytes for the filename
        :param set existing_filenames:  Set of existing filenames to avoid
        collisions with (in addition to those in the staging area, if provided).
        :return str:  Suitable file name
        """
        clean_filename = url.split("/")[-1].split("?")[0].split("#")[0]
        if re.match(r"[^.]+\.[a-zA-Z0-9]{1,10}", clean_filename):
            base_filename = clean_filename
        else:
            base_filename = default_name + default_ext

        # remove some problematic characters
        base_filename = re.sub(r"[:~]", "", base_filename)

        if existing_filenames is None:
            existing_filenames = set()
        if type(existing_filenames) is not set:
            # Could force set() here, but likely would be forcing in a loop
            raise TypeError("existing_filenames must be a set")

        # Split base filename into name and extension
        if '.' in base_filename:
            name_part, ext_part = base_filename.rsplit('.', 1)
            ext_part = '.' + ext_part
        else:
            name_part = base_filename
            ext_part = ''

        # Truncate base filename if it exceeds max_bytes
        if len(base_filename.encode('utf-8')) > max_bytes:
            # Reserve space for extension
            available_bytes = max_bytes - len(ext_part.encode('utf-8'))
            if available_bytes <= 0:
                # If extension is too long, use minimal name
                name_part = default_name
                ext_part = default_ext
                available_bytes = max_bytes - len(ext_part.encode('utf-8'))
            
            # Truncate name part to fit
            name_bytes = name_part.encode('utf-8')
            if len(name_bytes) > available_bytes:
                # Truncate byte by byte to ensure valid UTF-8
                while len(name_bytes) > available_bytes:
                    name_part = name_part[:-1]
                    name_bytes = name_part.encode('utf-8')
            
            base_filename = name_part + ext_part

        filename = base_filename

        if staging_area or existing_filenames:
            # Ensure the filename is unique in the staging area
            file_index = 1

            file_path = staging_area.joinpath(filename) if staging_area else None
            
            # Loop while collision in-memory OR on disk (if staging_area given)
            while (filename in existing_filenames) or (staging_area and file_path.exists()):
                # Calculate space needed for index suffix
                index_suffix = f"-{file_index}"
                
                # Check if filename with index would exceed max_bytes
                test_filename = name_part + index_suffix + ext_part
                if len(test_filename.encode('utf-8')) > max_bytes:
                    # Need to truncate name_part to make room for index
                    available_bytes = max_bytes - len((index_suffix + ext_part).encode('utf-8'))
                    if available_bytes <= 0:
                        # Extreme case - use minimal name
                        truncated_name = "f"
                    else:
                        # Truncate name_part to fit
                        truncated_name = name_part
                        name_bytes = truncated_name.encode('utf-8')
                        while len(name_bytes) > available_bytes:
                            truncated_name = truncated_name[:-1]
                            name_bytes = truncated_name.encode('utf-8')
                    
                    filename = truncated_name + index_suffix + ext_part
                else:
                    filename = test_filename
                
                file_index += 1
                if staging_area:
                    file_path = staging_area.joinpath(filename)

        return filename


def split_urls(url_string, allowed_schemes=None):
    """
    Split URL text by \n and commas.

    4CAT allows users to input lists by either separating items with a newline or a comma. This function will split URLs
    and also check for commas within URLs using schemes.

    Note: some urls may contain scheme (e.g., https://web.archive.org/web/20250000000000*/http://economist.com);
    this function will work so long as the inner scheme does not follow a comma (e.g., "http://,https://" would fail).
    """
    if allowed_schemes is None:
        allowed_schemes = ('http://', 'https://', 'ftp://', 'ftps://')
    potential_urls = []
    # Split the text by \n
    for line in url_string.split('\n'):
        # Handle commas that may exist within URLs
        parts = line.split(',')
        recombined_url = ""
        for part in parts:
            if part.startswith(allowed_schemes):  # Other schemes exist
                # New URL start detected
                if recombined_url:
                    # Already have a URL, add to list
                    potential_urls.append(recombined_url)
                # Start new URL
                recombined_url = part
            elif part:
                if recombined_url:
                    # Add to existing URL
                    recombined_url += "," + part
                else:
                    # No existing URL, start new
                    recombined_url = part
            else:
                # Ignore empty strings
                pass
        if recombined_url:
            # Add any remaining URL
            potential_urls.append(recombined_url)
    return potential_urls


def folder_size(path='.'):
    """
    Get the size of a folder using os.scandir for efficiency
    """
    total = 0
    for entry in os.scandir(path):
        if entry.is_file():
            total += entry.stat().st_size
        elif entry.is_dir():
            total += folder_size(entry.path)
    return total

def hash_to_md5(string: str) -> str:
    """
    Hash a string with an md5 hash.
    """
    return hashlib.md5(string.encode("utf-8")).hexdigest()