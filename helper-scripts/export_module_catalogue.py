#!/usr/bin/env python3
"""
Export the module catalogue as a static web page.

Writes a self-contained directory -- one HTML page, its stylesheets, JavaScript and
icons, and a single JSON file holding the data -- describing every data source and
processor in this checkout. The result can be served by any ordinary web server:
there is no Python, no database and no 4CAT API behind it.

The data is whatever `ProcessorMap` already computes for the catalogue inside a
running 4CAT, so the published page and the application page describe the same
modules and the same relationships. Extensions are deliberately left out, because
this describes an official 4CAT release rather than one installation's setup.

Run it from the repository root:

    python helper-scripts/export_module_catalogue.py --output dist/catalogue

and then look at the result with, for example:

    python -m http.server --directory dist/catalogue
"""
import argparse
import gzip
import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile

from datetime import datetime, timezone
from pathlib import Path

PATH_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PATH_ROOT))

from common.lib.module_loader import ModuleCollector  # noqa: E402
from common.lib.processor_map import ProcessorMap  # noqa: E402

# Raise this only when the published data changes in a way an older page cannot
# read; the page refuses a file it does not understand rather than showing gaps.
SCHEMA_VERSION = 1
DATA_FILE = "data/catalogue-v1.json"

PATH_STATIC = PATH_ROOT.joinpath("webtool", "static")

# The page: a standalone shell, with the catalogue markup that 4CAT's own page uses
# pasted into it where the marker sits, so the two pages cannot drift apart.
SHELL = PATH_STATIC.joinpath("module-catalog", "index.html")
LIVE_PAGE = PATH_ROOT.joinpath("webtool", "templates", "module-catalog.html")
SHARED_BODY = PATH_ROOT.joinpath("webtool", "templates", "components", "module-catalog-body.html")
BODY_MARKER = "<!--CATALOGUE-BODY-->"

# The stylesheets to publish. What each is built from is read from the files
# themselves rather than listed here, so a change to 4CAT's styling needs no change
# to this script.
STYLESHEETS = ("fourcat-new.css", "module-catalog.css")

# Files that are neither the page nor a stylesheet, as (file in this repository,
# place in the bundle). The icons the catalogue draws: ordinary ones in the solid
# style, data source ones in the brand style.
ASSETS = (
    ("webtool/static/js/module-catalog.js", "assets/catalogue.js"),
    ("webtool/static/fontawesome/css/fontawesome.css", "assets/fontawesome/css/fontawesome.css"),
    ("webtool/static/fontawesome/css/solid.css", "assets/fontawesome/css/solid.css"),
    ("webtool/static/fontawesome/css/brands.css", "assets/fontawesome/css/brands.css"),
    ("webtool/static/fontawesome/webfonts/fa-solid-900.woff2", "assets/fontawesome/webfonts/fa-solid-900.woff2"),
    ("webtool/static/fontawesome/webfonts/fa-brands-400.woff2", "assets/fontawesome/webfonts/fa-brands-400.woff2"),
)

# Another file a stylesheet pulls in: `url(...)` covers both plain references and
# `@import url(...)`; the second half catches an `@import` written without `url`.
CSS_REFERENCE = re.compile(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)|@import\s+['"]([^'"]+)['"]""")


class ExportConfig:
    """
    The little bit of configuration the module loader needs, with no database.

    Loading modules only takes a few paths and the list of enabled extensions. The
    empty extension list is what keeps extensions out of the published catalogue,
    whether or not any happen to be installed in this checkout.
    """

    def __init__(self, scratch):
        self.settings = {
            "PATH_ROOT": PATH_ROOT,
            "PATH_DATA": scratch,
            "PATH_LOGS": scratch.joinpath("logs"),
            "PATH_EXTENSIONS": PATH_ROOT.joinpath("config", "extensions"),
            "extensions.enabled": {},
        }

    def get(self, attribute_name, default=None, is_json=False, user=None, tags=None):
        return self.settings.get(attribute_name, default)

    def load_user_settings(self, *args, **kwargs):
        pass


class ErrorCollector(logging.Handler):
    """
    Remembers the errors reported while the map is built.

    `ProcessorMap` is deliberately forgiving: a module it cannot read is logged and
    left out so that one broken module cannot take down the whole map. That is right
    for a running 4CAT and wrong for a published catalogue, where it would quietly
    drop a module from the public list, so the export reads these back and stops.
    """

    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.errors = []

    def emit(self, record):
        self.errors.append(record.getMessage())


def git(*arguments, default=""):
    """Ask git something about this checkout; `default` if git cannot answer."""
    try:
        result = subprocess.run(["git", "-C", str(PATH_ROOT), *arguments],
                                capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return default
    return result.stdout.strip() if result.returncode == 0 else default


def build_map(scratch):
    """
    Load this checkout's core modules and build the map of how they connect.

    Stops rather than returning a short catalogue. There are two separate ways a
    module can go missing and both are checked, because neither implies the other:
    it can fail to import at all (the module loader records that), or it can import
    and then fail while the map reads its declared compatibility and output (the map
    records that, and its own module list comes up short).
    """
    config = ExportConfig(scratch)
    config.get("PATH_LOGS").mkdir(parents=True, exist_ok=True)

    modules = ModuleCollector(config=config)
    if modules.missing_modules:
        raise RuntimeError(
            "these modules could not be loaded, so the catalogue would be missing "
            "them: %s. Install what they need and try again." % ", ".join(sorted(modules.missing_modules)))

    collector = ErrorCollector()
    log = logging.getLogger("module-catalogue-export")
    log.addHandler(collector)
    catalogue_map = ProcessorMap(modules, config, logger=log)

    dropped = sorted(set(modules.processors) - set(catalogue_map.processors))
    if dropped:
        raise RuntimeError("these modules loaded but could not be read into the map, so the "
                           "catalogue would be missing them: %s" % ", ".join(dropped))
    if collector.errors:
        raise RuntimeError("the map reported problems while it was being built, so the "
                           "catalogue may be wrong:\n  %s" % "\n  ".join(collector.errors))

    return catalogue_map


def build_snapshot(catalogue_map, source):
    """
    The published data: a short entry for every module to browse and search, and the
    full detail for each, shown once a visitor opens one. Both are exactly what the
    live catalogue's API returns, sorted so that two exports of the same commit
    produce the same file.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "source": source,
        "catalogue": sorted(catalogue_map.catalogue(), key=lambda entry: entry["type"]),
        "modules": {module: catalogue_map.processor(module)
                    for module in sorted(catalogue_map.processors)},
    }


def prepare_output(output):
    """
    Make an empty output directory, replacing an earlier export.

    A directory holding anything other than a previous export is left alone: better
    to stop than to empty out a directory that turns out to be something else.
    """
    if output.exists() and any(output.iterdir()):
        if not output.joinpath("manifest.json").exists():
            raise RuntimeError("%s is not empty and does not look like an earlier catalogue "
                               "export (it has no manifest.json), so it was left untouched" % output)
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)


def copy_assets(output):
    """Copy the files that are neither the page nor a stylesheet."""
    for repository_path, bundle_path in ASSETS:
        origin = PATH_ROOT.joinpath(repository_path)
        if not origin.exists():
            raise RuntimeError("the catalogue page needs %s, which does not exist" % repository_path)
        destination = output.joinpath(bundle_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, destination)


def copy_stylesheets(output):
    """
    Copy 4CAT's own styling, so the published page looks like the catalogue inside
    4CAT and keeps looking like it while the design is being worked on.

    Which files that means is read from the stylesheets themselves: fourcat-new.css
    names every part it is built from, and each of those may pull in more, down to
    background images. Following that from the top means adding or removing a piece
    of 4CAT's styling needs no change here. Everything must sit under the static
    folder, so a reference pointing anywhere else stops the export rather than
    publishing a page missing its styling.
    """
    copied = set()
    queue = [PATH_STATIC.joinpath("css", name) for name in STYLESHEETS]

    while queue:
        origin = queue.pop().resolve()
        if origin in copied:
            continue
        if not origin.exists():
            raise RuntimeError("4CAT's styling refers to %s, which does not exist" % origin)
        try:
            place = origin.relative_to(PATH_STATIC)
        except ValueError:
            raise RuntimeError("4CAT's styling refers to %s, which is outside the static "
                               "folder and so cannot be published" % origin)

        copied.add(origin)
        destination = output.joinpath("assets", place)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, destination)

        if origin.suffix == ".css":
            for match in CSS_REFERENCE.finditer(origin.read_text(encoding="utf-8")):
                reference = (match.group(1) or match.group(2) or "").strip()
                if not reference or reference.startswith("data:"):
                    continue
                # A stylesheet pointing at another server would make every visitor's
                # browser fetch part of this page from somewhere else, which is what
                # publishing a self-contained copy is meant to avoid -- and which
                # nobody would notice, because the page still looks right.
                if reference.startswith(("http://", "https://", "//")):
                    raise RuntimeError(
                        "%s loads %s from another server. Everything this page needs has to be "
                        "in 4CAT itself, so put a copy in webtool/static and point at that."
                        % (place, reference))
                queue.append(origin.parent.joinpath(reference))

    return len(copied)


def write_page(output):
    """
    Write the page, with the catalogue markup 4CAT's own page uses pasted into it.

    Both pages read that markup from one file so they cannot drift apart, which only
    holds while it stays plain HTML and while 4CAT's page really does use it. Both
    are checked here, because either would otherwise fail quietly: a template tag
    would be published as visible nonsense, and a page that stopped sharing the
    markup would simply start describing something else.
    """
    body = SHARED_BODY.read_text(encoding="utf-8")
    for syntax in ("{{", "{%", "{#"):
        raise_at = body.find(syntax)
        if raise_at != -1:
            raise RuntimeError("%s contains template syntax (%s), but it has to be plain HTML: "
                               "nothing here can fill it in. Anything needing a value from 4CAT "
                               "belongs in %s instead." % (SHARED_BODY.name, syntax, LIVE_PAGE.name))

    if SHARED_BODY.name not in LIVE_PAGE.read_text(encoding="utf-8"):
        raise RuntimeError("%s no longer uses %s, so 4CAT's catalogue and the published one "
                           "would no longer show the same thing" % (LIVE_PAGE.name, SHARED_BODY.name))

    shell = SHELL.read_text(encoding="utf-8")
    if BODY_MARKER not in shell:
        raise RuntimeError("%s no longer contains %s, so there is nowhere to put the "
                           "catalogue markup" % (SHELL.name, BODY_MARKER))

    output.joinpath("index.html").write_text(shell.replace(BODY_MARKER, body), encoding="utf-8")


def export(output, source):
    """Write the whole bundle and return what should be reported about it."""
    prepare_output(output)

    with tempfile.TemporaryDirectory(prefix="4cat-catalogue-") as scratch:
        catalogue_map = build_map(Path(scratch))
        snapshot = build_snapshot(catalogue_map, source)

    data_file = output.joinpath(DATA_FILE)
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n"
    data_file.write_text(data, encoding="utf-8")

    write_page(output)
    stylesheets = copy_stylesheets(output)
    copy_assets(output)
    output.joinpath("manifest.json").write_text(json.dumps({
        "format_version": SCHEMA_VERSION,
        "fourcat_version": source["fourcat_version"],
        "git_tag": source["git_tag"],
        "git_commit": source["git_commit"],
        "generated_at": source["generated_at"],
        "data_file": DATA_FILE,
    }, indent=2) + "\n", encoding="utf-8")

    encoded = data.encode("utf-8")
    return {
        "modules": len(snapshot["catalogue"]),
        "datasources": len([e for e in snapshot["catalogue"] if e["is_datasource"]]),
        "stylesheets": stylesheets,
        "bytes": len(encoded),
        "gzipped": len(gzip.compress(encoded)),
        "sha256": hashlib.sha256(encoded).hexdigest(),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", required=True, type=Path,
                        help="directory to write the catalogue to")
    parser.add_argument("--version", help="the 4CAT version this describes (default: the VERSION file)")
    parser.add_argument("--tag", help="the release tag this describes (default: asked of git)")
    parser.add_argument("--commit", help="the commit this describes (default: asked of git)")
    parser.add_argument("--generated-at", help="timestamp to record (default: the commit's own date, "
                                               "so re-exporting a release reproduces it exactly)")
    arguments = parser.parse_args()

    # only the first line of VERSION is the version; the rest of the file explains
    # what it is for
    version_file = PATH_ROOT.joinpath("VERSION")
    source = {
        "fourcat_version": arguments.version
            or (version_file.read_text().splitlines()[0].strip() if version_file.exists() else "unknown"),
        "git_tag": arguments.tag or git("describe", "--tags", "--always", default="unknown"),
        "git_commit": arguments.commit or git("rev-parse", "HEAD", default="unknown"),
        "generated_at": arguments.generated_at or git("show", "-s", "--format=%cI", "HEAD")
            or datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = export(arguments.output, source)
    except RuntimeError as e:
        sys.exit("Nothing was published: %s" % e)

    print("4CAT %s (tag %s, commit %s)" % (source["fourcat_version"], source["git_tag"], source["git_commit"][:8]))
    print("%i modules, of which %i data sources" % (result["modules"], result["datasources"]))
    print("%i styling files copied from 4CAT" % result["stylesheets"])
    print("%s: %.1f kB, %.1f kB compressed, sha256 %s"
          % (DATA_FILE, result["bytes"] / 1000, result["gzipped"] / 1000, result["sha256"]))
    print("written to %s" % arguments.output.resolve())
    print("look at it with: python -m http.server --directory %s" % arguments.output)


if __name__ == "__main__":
    main()
