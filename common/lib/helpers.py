"""
Miscellaneous helper functions for the 4CAT backend
"""
import subprocess
import requests
import datetime
import smtplib
import fnmatch
import socket
import copy
import time
import json
import math
import ssl
import re
import os
import io

from collections.abc import MutableMapping
from html.parser import HTMLParser
from pathlib import Path
from calendar import monthrange
from packaging import version

from common.lib.user_input import UserInput
from common.config_manager import config


def init_datasource(database, logger, queue, name):
    """
    Initialize data source

    Queues jobs to scrape the boards that were configured to be scraped in the
    4CAT configuration file. If none were configured, nothing happens.

    :param Database database:  Database connection instance
    :param Logger logger:  Log handler
    :param JobQueue queue:  Job Queue instance
    :param string name:  ID of datasource that is being initialised
    """
    pass


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
    if type(file) == bytearray:
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


def get_git_branch():
    """
    Get current git branch

    If the 4CAT root folder is a git repository, this function will return the
    name of the currently checked-out branch. If the folder is not a git
    repository or git is not installed an empty string is returned.
    """
    try:
        cwd = os.getcwd()
        os.chdir(config.get('PATH_ROOT'))
        branch = subprocess.run(["git", "branch", "--show-current"], stdout=subprocess.PIPE)
        os.chdir(cwd)
        if branch.returncode != 0:
            raise ValueError()
        return branch.stdout.decode("utf-8").strip()
    except (subprocess.SubprocessError, ValueError, FileNotFoundError):
        return ""


def get_software_commit():
    """
    Get current 4CAT commit hash

    Reads a given version file and returns the first string found in there
    (up until the first space). On failure, return an empty string.

    Use `get_software_version()` instead if you need the release version
    number rather than the precise commit hash.

    If no version file is available, run `git show` to test if there is a git
    repository in the 4CAT root folder, and if so, what commit is currently
    checked out in it.

    :return str:  4CAT git commit hash
    """
    versionpath = config.get('PATH_ROOT').joinpath(config.get('path.versionfile'))

    if versionpath.exists() and not versionpath.is_file():
        return ""

    if not versionpath.exists():
        # try git command line within the 4CAT root folder
        # if it is a checked-out git repository, it will tell us the hash of
        # the currently checked-out commit
        try:
            cwd = os.getcwd()
            os.chdir(config.get('PATH_ROOT'))
            show = subprocess.run(["git", "show"], stderr=subprocess.PIPE, stdout=subprocess.PIPE)
            os.chdir(cwd)
            if show.returncode != 0:
                raise ValueError()
            return show.stdout.decode("utf-8").split("\n")[0].split(" ")[1]
        except (subprocess.SubprocessError, IndexError, TypeError, ValueError, FileNotFoundError):
            return ""

    try:
        with open(versionpath, "r", encoding="utf-8", errors="ignore") as versionfile:
            version = versionfile.readline().split(" ")[0]
            return version
    except OSError:
        return ""

def get_software_version():
    """
    Get current 4CAT version

    This is the actual software version, i.e. not the commit hash (see
    `get_software_hash()` for that). The current version is stored in a file
    with a canonical location: if the file doesn't exist, an empty string is
    returned.

    :return str:  Software version, for example `1.37`.
    """
    current_version_file = Path(config.get("PATH_ROOT"), "config/.current-version")
    if not current_version_file.exists():
        return ""

    with current_version_file.open() as infile:
        return infile.readline().strip()

def get_github_version(timeout=5):
    """
    Get latest release tag version from GitHub

    Will raise a ValueError if it cannot retrieve information from GitHub.

    :param int timeout:  Timeout in seconds for HTTP request

    :return tuple:  Version, e.g. `1.26`, and release URL.
    """
    repo_url = config.get("4cat.github_url")
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


def timify_long(number):
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
        components.append("%i month%s" % (months, "s" if months != 1 else ""))
        number -= (months * month_length)

    week_length = 7 * 86400
    weeks = math.floor(number / week_length)
    if weeks:
        components.append("%i week%s" % (weeks, "s" if weeks != 1 else ""))
        number -= (weeks * week_length)

    day_length = 86400
    days = math.floor(number / day_length)
    if days:
        components.append("%i day%s" % (days, "s" if days != 1 else ""))
        number -= (days * day_length)

    hour_length = 3600
    hours = math.floor(number / hour_length)
    if hours:
        components.append("%i hour%s" % (hours, "s" if hours != 1 else ""))
        number -= (hours * hour_length)

    minute_length = 60
    minutes = math.floor(number / minute_length)
    if minutes:
        components.append("%i minute%s" % (minutes, "s" if minutes != 1 else ""))

    if not components:
        components.append("less than a minute")

    last_str = components.pop()
    time_str = ""
    if components:
        time_str = ", ".join(components)
        time_str += " and "

    return time_str + last_str


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


def call_api(action, payload=None):
    """
    Send message to server

    Calls the internal API and returns interpreted response.

    :param str action: API action
    :param payload: API payload

    :return: API response, or timeout message in case of timeout
    """
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    connection.settimeout(15)
    connection.connect((config.get('API_HOST'), config.get('API_PORT')))

    msg = json.dumps({"request": action, "payload": payload})
    connection.sendall(msg.encode("ascii", "ignore"))

    try:
        response = ""
        while True:
            bytes = connection.recv(2048)
            if not bytes:
                break

            response += bytes.decode("ascii", "ignore")
    except (socket.timeout, TimeoutError):
        response = "(Connection timed out)"

    try:
        connection.shutdown(socket.SHUT_RDWR)
    except OSError:
        # already shut down automatically
        pass
    connection.close()

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return response


def get_interval_descriptor(item, interval):
    """
    Get interval descriptor based on timestamp

    :param dict item:  Item to generate descriptor for, should have a
    "timestamp" key
    :param str interval:  Interval, one of "all", "overall", "year",
    "month", "week", "day"
    :return str:  Interval descriptor, e.g. "overall", "2020", "2020-08",
    "2020-43", "2020-08-01"
    """
    if interval in ("all", "overall"):
        return interval

    if "timestamp" not in item:
        raise ValueError("No date available for item in dataset")

    # Catch cases where a custom timestamp has an epoch integer as value.
    try:
        timestamp = int(item["timestamp"])
        try:
            timestamp = datetime.datetime.fromtimestamp(timestamp)
        except (ValueError, TypeError) as e:
            raise ValueError("Invalid timestamp '%s'" % str(item["timestamp"]))
    except:
        try:
            timestamp = datetime.datetime.strptime(item["timestamp"], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError) as e:
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
    test_key = list(intervals.keys())[0]

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


def send_email(recipient, message):
    """
    Send an e-mail using the configured SMTP settings

    Just a thin wrapper around smtplib, so we don't have to repeat ourselves.
    Exceptions are to be handled outside the function.

    :param list recipient:  Recipient e-mail addresses
    :param MIMEMultipart message:  Message to send
    """
    # Create a secure SSL context
    context = ssl.create_default_context()

    # Decide which connection type
    with smtplib.SMTP_SSL(config.get('mail.server'), port=config.get('mail.port', 0), context=context) if config.get(
            'mail.ssl') == 'ssl' else smtplib.SMTP(config.get('mail.server'),
                                                   port=config.get('mail.port', 0)) as server:
        if config.get('mail.ssl') == 'tls':
            # smtplib.SMTP adds TLS context here
            server.starttls(context=context)

        # Log in
        if config.get('mail.username') and config.get('mail.password'):
            server.ehlo()
            server.login(config.get('mail.username'), config.get('mail.password'))

        # Send message
        if type(message) == str:
            server.sendmail(config.get('mail.noreply'), recipient, message)
        else:
            server.sendmail(config.get('mail.noreply'), recipient, message.as_string())


def flatten_dict(d: MutableMapping, parent_key: str = '', sep: str = '.'):
    """
    Return a flattened dictionary where nested dictionary objects are given new
    keys using the partent key combined using the seperator with the child key.

    Lists will be converted to json strings via json.dumps()

    :param MutableMapping d:  Dictionary like object
    :param str partent_key: The original parent key prepending future nested keys
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

    def _check_list(l):
        return [sets_to_lists(item) if isinstance(item, MutableMapping) else _check_list(item) if isinstance(item, (
        set, list)) else item for item in l]

    def _sets_to_lists_gen(d):
        for k, v in d.items():
            if isinstance(v, MutableMapping):
                yield k, sets_to_lists(v)
            elif isinstance(v, (list, set)):
                yield k, _check_list(v)
            else:
                yield k, v

    return dict(_sets_to_lists_gen(d))

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
