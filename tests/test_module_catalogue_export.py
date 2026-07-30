"""
Tests for the static module catalogue export (helper-scripts/export_module_catalogue.py).

The export publishes a page describing every data source and processor in a 4CAT
release, to be served by an ordinary web server with no 4CAT behind it. Three things
can go wrong quietly, and those are what these tests are mostly about:

* the catalogue could come out short -- a module that failed to load, or that the
  map could not read, would simply be absent, and a page listing 157 of 158 modules
  looks exactly like a page listing all of them;
* the published page could drift away from the one inside 4CAT, which is the whole
  reason the two share their markup, their stylesheets and their JavaScript;
* the page could claim to describe a 4CAT release when it describes somebody's work
  in progress.

So the export refuses to publish a partial, drifted or mislabelled result, and the
tests below check that each of those refusals actually happens, as well as running
one real export of this checkout and inspecting what it produced.
"""
import importlib.util
import json
import re
import shutil

from pathlib import Path

import pytest

PATH_ROOT = Path(__file__).resolve().parent.parent

# Fixed provenance, so tests can check these exact values come out the other end.
PROVENANCE = {
    "kind": "release",
    "fourcat_version": "9.99",
    "release_tag": "v9.99",
    "git_describe": "v9.99",
    "git_commit": "0123456789abcdef0123456789abcdef01234567",
    "generated_at": "2026-01-01T00:00:00+00:00",
}


@pytest.fixture(scope="module")
def export():
    """The export script. Loaded by path, because helper-scripts is not a package."""
    path = PATH_ROOT.joinpath("helper-scripts", "export_module_catalogue.py")
    spec = importlib.util.spec_from_file_location("export_module_catalogue", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bundle(export, tmp_path_factory):
    """One real export of this checkout, shared by every test that reads it."""
    output = tmp_path_factory.mktemp("catalogue").joinpath("bundle")
    export.export(output, dict(PROVENANCE))
    return output


@pytest.fixture(scope="module")
def snapshot(bundle):
    """The published data file."""
    return json.loads(bundle.joinpath("data", "catalogue-v1.json").read_text(encoding="utf-8"))


# --- helpers ---------------------------------------------------------------

# A file a page or stylesheet loads as part of itself: a <link>, anything with a
# src, or a url() in CSS. Deliberately not <a href>, which is somewhere a visitor
# can choose to go rather than something the page fetches.
RESOURCE = re.compile(
    r"""<link\b[^>]*\bhref\s*=\s*["']([^"']+)["']"""
    r"""|\bsrc\s*=\s*["']([^"']+)["']"""
    r"""|url\(\s*["']?([^"')]+?)["']?\s*\)""",
    re.IGNORECASE)


def resources(text):
    """Every file the given HTML or CSS loads as part of itself."""
    found = set()
    for match in RESOURCE.finditer(text):
        reference = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        if reference and not reference.startswith("data:"):
            found.add(reference)
    return found


def local_references(text):
    """The resources that are expected to sit on this same server."""
    return {reference.split("?")[0].split("#")[0] for reference in resources(text)
            if not reference.startswith(("http://", "https://", "//", "#"))}


def loaded_module_types(export, scratch, extensions):
    """
    The modules this checkout loads, with `extensions` saying which installed
    extensions are switched on.

    ModuleCollector gathers what it finds into dictionaries held on the class, and
    only hands the instance its own copy once the walk has finished. Every loader in
    the process therefore adds to one shared pile, and a second load can never come
    back with fewer modules than the first -- comparing two loads without clearing
    that pile silently compares a set with itself. So each call empties it first and
    puts back exactly what was there afterwards.
    """
    collector = export.ModuleCollector
    shared = ("workers", "processors", "datasources", "ignore")
    saved = {name: getattr(collector, name) for name in shared}
    collector.workers, collector.processors, collector.datasources, collector.ignore = {}, {}, {}, []
    try:
        config = export.ExportConfig(scratch)
        config.settings["extensions.enabled"] = extensions
        config.get("PATH_LOGS").mkdir(parents=True, exist_ok=True)
        return set(collector(config=config).processors)
    finally:
        for name, value in saved.items():
            setattr(collector, name, value)


def fake_pages(export, monkeypatch, tmp_path, body="<p id=\"pc-search\">markup</p>",
               live="{% include 'components/module-catalog-body.html' %}",
               shell="<body>\n<!--CATALOGUE-BODY-->\n</body>"):
    """Stand-ins for the three files the page is assembled from, so the checks that
    guard them can be tried without touching the real ones."""
    fragment = tmp_path.joinpath("module-catalog-body.html")
    page = tmp_path.joinpath("module-catalog.html")
    outer = tmp_path.joinpath("index.html")
    for path, text in ((fragment, body), (page, live), (outer, shell)):
        path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(export, "SHARED_BODY", fragment)
    monkeypatch.setattr(export, "LIVE_PAGE", page)
    monkeypatch.setattr(export, "SHELL", outer)


def copy_of(bundle, tmp_path, name="bundle"):
    """A throwaway copy of the exported bundle, to be broken in one specific way."""
    copy = tmp_path.joinpath(name)
    shutil.copytree(bundle, copy)
    return copy


def rewrite_json(path, change):
    """Read a JSON file, let `change` alter it, and write it back."""
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


class FakeLoader:
    """A module loader that reports exactly what a test tells it to."""

    def __init__(self, processors=(), missing=None):
        self.processors = {name: type(name, (), {}) for name in processors}
        self.missing_modules = missing or {}

    def __call__(self, config=None):
        return self


# --- the catalogue must not come out short ---------------------------------

def test_every_loaded_module_reaches_the_catalogue(export, bundle, snapshot, tmp_path):
    """The published catalogue lists every module this checkout loads -- nothing is
    dropped on the way from the loader, through the map, into the file."""
    catalogue_map = export.build_map(tmp_path)
    published = {entry["type"] for entry in snapshot["catalogue"]}
    assert published == set(catalogue_map.processors)
    assert len(published) == len(snapshot["catalogue"]), "a module is listed twice"


def test_every_listed_module_has_its_full_details(snapshot):
    """Opening any module in the catalogue has to find something to show."""
    listed = {entry["type"] for entry in snapshot["catalogue"]}
    assert set(snapshot["modules"]) == listed
    for module_type, detail in snapshot["modules"].items():
        assert detail is not None, "%s has no details" % module_type
        assert detail["type"] == module_type


def test_a_module_that_will_not_load_stops_the_export(export, monkeypatch, tmp_path):
    monkeypatch.setattr(export, "ModuleCollector",
                        FakeLoader(processors=["a"], missing={"numpy": ["processors.a"]}))
    with pytest.raises(RuntimeError, match="could not be loaded"):
        export.build_map(tmp_path)


def test_a_module_the_map_cannot_read_stops_the_export(export, monkeypatch, tmp_path):
    """A module can load and still fall out while the map reads it. The loader
    reports nothing wrong in that case, so the export compares the two itself."""
    class HalfBuiltMap:
        def __init__(self, modules, config, logger=None):
            self.processors = {"a": modules.processors["a"]}  # "b" fell out

    monkeypatch.setattr(export, "ModuleCollector", FakeLoader(processors=["a", "b"]))
    monkeypatch.setattr(export, "ProcessorMap", HalfBuiltMap)
    with pytest.raises(RuntimeError, match="could not be read into the map") as raised:
        export.build_map(tmp_path)
    assert "b" in str(raised.value), "the export does not say which module went missing"


def test_a_problem_reported_while_building_stops_the_export(export, monkeypatch, tmp_path):
    """The map keeps going when a module's compatibility is miscalibrated, and says
    so in the log. For a published catalogue that is not good enough."""
    class ComplainingMap:
        def __init__(self, modules, config, logger=None):
            self.processors = dict(modules.processors)
            logger.error("processor 'a' has a 'compatibility' that is str")

    monkeypatch.setattr(export, "ModuleCollector", FakeLoader(processors=["a"]))
    monkeypatch.setattr(export, "ProcessorMap", ComplainingMap)
    with pytest.raises(RuntimeError, match="reported problems"):
        export.build_map(tmp_path)


# --- extensions are not published ------------------------------------------

def test_the_loader_is_told_to_ignore_every_extension(export, tmp_path):
    """Whatever is installed on the machine running the export, no extension is
    enabled while the catalogue is built."""
    config = export.ExportConfig(tmp_path)
    assert config.get("extensions.enabled") == {}
    assert config.get("PATH_EXTENSIONS") == PATH_ROOT.joinpath("config", "extensions")


def test_installed_extensions_do_not_reach_the_catalogue(export, snapshot, tmp_path):
    """
    Where this machine has extensions installed, nothing they add is published.

    What an extension adds is worked out by loading twice and comparing, rather than
    by reading each module's own is_extension flag: that flag records where a module
    was first come across, so a core module an extension happens to import is
    labelled as the extension's.

    Skipped where there is genuinely nothing to leave out, so that a pass always
    means something was checked.
    """
    extensions_folder = export.ExportConfig(tmp_path).get("PATH_EXTENSIONS")
    installed = ([path.name for path in extensions_folder.iterdir() if path.is_dir()]
                 if extensions_folder.is_dir() else [])
    if not installed:
        pytest.skip("no extensions are installed here, so there is nothing to leave out")

    everything = loaded_module_types(export, tmp_path, {name: {"enabled": True} for name in installed})
    core = loaded_module_types(export, tmp_path, {})
    from_extensions = everything - core
    if not from_extensions:
        pytest.skip("the installed extensions (%s) add no modules" % ", ".join(installed))

    published = {entry["type"] for entry in snapshot["catalogue"]}
    assert not (published & from_extensions), \
        "these came from an extension and should not be published: %s" % sorted(published & from_extensions)
    assert published == core, "the catalogue is not exactly this release's core modules"


# --- the published data ----------------------------------------------------

def test_the_data_file_says_what_it_is(snapshot, export):
    assert snapshot["schema_version"] == export.SCHEMA_VERSION
    assert set(snapshot) == {"schema_version", "source", "catalogue", "modules"}
    assert snapshot["source"] == PROVENANCE


def test_the_manifest_describes_the_bundle(bundle, snapshot, export):
    """The manifest is what the site reads first, so it has to name the data file
    and carry the provenance the export was given."""
    manifest = json.loads(bundle.joinpath("manifest.json").read_text(encoding="utf-8"))
    assert manifest["format_version"] == export.FORMAT_VERSION
    assert manifest["data_schema_version"] == export.SCHEMA_VERSION == snapshot["schema_version"]
    assert manifest["source"] == PROVENANCE
    assert manifest["source"] == snapshot["source"], "the manifest and the data file disagree"
    assert manifest["data_file"] == export.DATA_FILE
    assert bundle.joinpath(manifest["data_file"]).exists()


def test_the_data_file_is_sorted(snapshot):
    """Sorted so that two releases can be compared by reading the difference."""
    assert [entry["type"] for entry in snapshot["catalogue"]] == sorted(snapshot["modules"])
    assert list(snapshot["modules"]) == sorted(snapshot["modules"])


def test_two_exports_of_the_same_checkout_are_identical(export, tmp_path):
    """Nothing about the machine or the moment leaks into the published files, so a
    release can be exported again and checked against what was published."""
    first, second = tmp_path.joinpath("first"), tmp_path.joinpath("second")
    export.export(first, dict(PROVENANCE))
    export.export(second, dict(PROVENANCE))
    for name in ("data/catalogue-v1.json", "manifest.json", "index.html"):
        assert first.joinpath(name).read_bytes() == second.joinpath(name).read_bytes(), \
            "%s came out differently the second time" % name


def test_a_module_entry_carries_what_the_page_shows(snapshot):
    """The page draws each module from these, so an entry missing them would render
    blank rather than fail."""
    for entry in snapshot["catalogue"]:
        assert entry["type"] and entry["title"]
        for field in ("tags", "is_datasource", "is_filter", "description"):
            assert field in entry, "%s has no %s" % (entry["type"], field)
    for module_type, detail in snapshot["modules"].items():
        for field in ("how_to_run", "followups", "output_shape"):
            assert field in detail, "%s has no %s" % (module_type, field)


# --- what is published has to be what it claims to be ----------------------

def test_an_exactly_tagged_commit_is_published_as_a_release(export, monkeypatch):
    monkeypatch.setattr(export, "git", lambda *arguments, default="": {
        ("describe", "--exact-match", "--tags", "HEAD"): "v1.56",
        ("describe", "--tags", "--always"): "v1.56",
        ("rev-parse", "HEAD"): "a" * 40,
    }.get(arguments, default))
    source = export.describe_source()
    assert source["kind"] == "release"
    assert source["release_tag"] == "v1.56"


def test_a_commit_after_a_tag_is_published_as_a_snapshot(export, monkeypatch):
    """git describe answers "v1.55-145-ga6e11f52e" for a commit 145 after v1.55.
    Reading a release tag out of that would put a version on the public page that
    was never released, so a snapshot has no release tag at all."""
    monkeypatch.setattr(export, "git", lambda *arguments, default="": {
        ("describe", "--exact-match", "--tags", "HEAD"): "",   # git found no exact tag
        ("describe", "--tags", "--always"): "v1.55-145-ga6e11f52e",
        ("rev-parse", "HEAD"): "b" * 40,
    }.get(arguments, default))
    source = export.describe_source()
    assert source["kind"] == "development_snapshot"
    assert source["release_tag"] is None
    assert source["git_describe"] == "v1.55-145-ga6e11f52e"


def test_a_named_release_tag_is_taken_at_its_word(export, monkeypatch):
    """A release build passes the tag, because a shallow checkout has no tags for
    git to find and the release would otherwise be published as a snapshot."""
    monkeypatch.setattr(export, "git", lambda *arguments, default="": {
        ("describe", "--tags", "--always"): "unknown",
        ("rev-parse", "HEAD"): "c" * 40,
    }.get(arguments, default))
    source = export.describe_source(release_tag="v1.56")
    assert source["kind"] == "release"
    assert source["release_tag"] == "v1.56"


def test_provenance_can_be_supplied_rather_than_asked_of_git(export, monkeypatch):
    """
    A release is exported inside a container built from a shallow checkout, where git
    knows almost nothing -- no tags, and sometimes no repository at all. Everything
    recorded about the source can therefore be passed in instead, worked out where
    git does have the full history.
    """
    monkeypatch.setattr(export, "git", lambda *arguments, default="": default)
    source = export.describe_source(version="1.56", release_tag="v1.56", commit="d" * 40,
                                    generated_at="2026-07-29T15:41:03+02:00",
                                    git_describe="v1.56")
    assert source == {
        "kind": "release",
        "fourcat_version": "1.56",
        "release_tag": "v1.56",
        "git_describe": "v1.56",
        "git_commit": "d" * 40,
        "generated_at": "2026-07-29T15:41:03+02:00",
    }


def test_the_page_says_which_release_it_is_showing(bundle):
    """Both wordings live in the page, so it can name a release or own up to being
    a snapshot without the export having to write different pages."""
    page = bundle.joinpath("index.html").read_text(encoding="utf-8")
    assert "Catalogue for 4CAT" in page
    assert "Development snapshot" in page
    assert "release_tag" in page and "kind" in page


# --- the two catalogues must not drift apart -------------------------------

def test_the_published_page_uses_4cats_own_catalogue_markup(export, bundle):
    """The published page and the one inside 4CAT show the same thing because they
    are built from the same markup, so it has to actually be in there."""
    page = bundle.joinpath("index.html").read_text(encoding="utf-8")
    fragment = export.SHARED_BODY.read_text(encoding="utf-8")
    assert fragment.strip() in page
    assert export.BODY_MARKER not in page, "the markup was never pasted in"
    for element in ("pc-detail-body", "pc-search", "pc-tag", "pc-catalogue", "pc-count"):
        assert element in page, "the page has no %s for the catalogue to draw into" % element


def test_4cats_own_page_uses_the_shared_markup_too(export):
    """The other half of the same promise: if 4CAT's page stopped including the
    shared markup the two would drift apart without anything failing."""
    live = export.LIVE_PAGE.read_text(encoding="utf-8")
    assert export.SHARED_BODY.name in live
    assert "pc-search" not in live, "4CAT's page has its own copy of the markup again"


def test_template_syntax_in_the_shared_markup_stops_the_export(export, monkeypatch, tmp_path):
    """Nothing fills in template tags for the published page, so they would be
    published as visible nonsense."""
    for syntax in ("{{ processor.type }}", "{% if x %}{% endif %}", "{# note #}"):
        fake_pages(export, monkeypatch, tmp_path, body="<p>%s</p>" % syntax)
        with pytest.raises(RuntimeError, match="plain HTML"):
            export.write_page(tmp_path.joinpath("out"))


def test_4cat_dropping_the_shared_markup_stops_the_export(export, monkeypatch, tmp_path):
    fake_pages(export, monkeypatch, tmp_path, live="<p>a page of its own again</p>")
    with pytest.raises(RuntimeError, match="no longer uses"):
        export.write_page(tmp_path.joinpath("out"))


def test_a_shell_with_nowhere_to_put_the_markup_stops_the_export(export, monkeypatch, tmp_path):
    fake_pages(export, monkeypatch, tmp_path, shell="<body>nothing here</body>")
    with pytest.raises(RuntimeError, match="nowhere to put"):
        export.write_page(tmp_path.joinpath("out"))


def test_the_markup_is_pasted_where_the_marker_was(export, monkeypatch, tmp_path):
    fake_pages(export, monkeypatch, tmp_path, body="<p id=\"pc-search\">here</p>",
               shell="<body>\nbefore\n<!--CATALOGUE-BODY-->\nafter\n</body>")
    output = tmp_path.joinpath("out")
    output.mkdir()
    export.write_page(output)
    page = output.joinpath("index.html").read_text(encoding="utf-8")
    assert page.index("before") < page.index("here") < page.index("after")


# --- 4CAT's styling comes along --------------------------------------------

def test_the_styling_follows_4cats_own_list(export, bundle):
    """The stylesheets to publish are read from the stylesheets themselves, so that
    changing how 4CAT looks needs no change to the export. Everything the top-level
    stylesheet names has to have come along."""
    for name in export.STYLESHEETS:
        assert bundle.joinpath("assets", "css", name).exists()
    top = PATH_ROOT.joinpath("webtool", "static", "css", "fourcat-new.css").read_text(encoding="utf-8")
    imported = local_references(top)
    assert imported, "fourcat-new.css named no other stylesheets -- has it moved?"
    for reference in imported:
        assert bundle.joinpath("assets", "css", reference).exists(), "%s was left behind" % reference


def test_a_stylesheet_loading_from_another_server_stops_the_export(export, monkeypatch, tmp_path):
    """A published page fetching part of itself from somewhere else would still look
    right, so nothing would draw attention to it."""
    static = tmp_path.joinpath("static", "css")
    static.mkdir(parents=True)
    static.joinpath("main.css").write_text("@import url('other.css');", encoding="utf-8")
    static.joinpath("other.css").write_text(
        ".x { mask-image: url('https://example.org/logo.svg'); }", encoding="utf-8")
    monkeypatch.setattr(export, "PATH_STATIC", tmp_path.joinpath("static"))
    monkeypatch.setattr(export, "STYLESHEETS", ("main.css",))
    with pytest.raises(RuntimeError, match="another server"):
        export.copy_stylesheets(tmp_path.joinpath("out"))


def test_a_stylesheet_reaching_outside_the_static_folder_stops_the_export(export, monkeypatch, tmp_path):
    static = tmp_path.joinpath("static", "css")
    static.mkdir(parents=True)
    tmp_path.joinpath("elsewhere.css").write_text("/* not publishable */", encoding="utf-8")
    static.joinpath("main.css").write_text("@import url('../../elsewhere.css');", encoding="utf-8")
    monkeypatch.setattr(export, "PATH_STATIC", tmp_path.joinpath("static"))
    monkeypatch.setattr(export, "STYLESHEETS", ("main.css",))
    with pytest.raises(RuntimeError, match="outside the static folder"):
        export.copy_stylesheets(tmp_path.joinpath("out"))


def test_styling_is_followed_all_the_way_down(export, monkeypatch, tmp_path):
    """A stylesheet can name another, which can name an image; all of it has to come
    along, and a loop between two stylesheets must not hang the export."""
    static = tmp_path.joinpath("static")
    static.joinpath("css").mkdir(parents=True)
    static.joinpath("img").mkdir()
    static.joinpath("img", "logo.svg").write_text("<svg/>", encoding="utf-8")
    static.joinpath("css", "main.css").write_text("@import url('deep.css');", encoding="utf-8")
    static.joinpath("css", "deep.css").write_text(
        "@import url('main.css'); .x { background: url('../img/logo.svg'); }", encoding="utf-8")
    monkeypatch.setattr(export, "PATH_STATIC", static)
    monkeypatch.setattr(export, "STYLESHEETS", ("main.css",))

    output = tmp_path.joinpath("out")
    assert export.copy_stylesheets(output) == 3
    assert output.joinpath("assets", "css", "deep.css").exists()
    assert output.joinpath("assets", "img", "logo.svg").exists()


def test_missing_styling_stops_the_export(export, monkeypatch, tmp_path):
    static = tmp_path.joinpath("static", "css")
    static.mkdir(parents=True)
    static.joinpath("main.css").write_text("@import url('gone.css');", encoding="utf-8")
    monkeypatch.setattr(export, "PATH_STATIC", tmp_path.joinpath("static"))
    monkeypatch.setattr(export, "STYLESHEETS", ("main.css",))
    with pytest.raises(RuntimeError, match="does not exist"):
        export.copy_stylesheets(tmp_path.joinpath("out"))


# --- the bundle stands on its own ------------------------------------------

def test_the_bundle_contains_everything_it_points_at(bundle):
    """Every file the page and its stylesheets name is in the bundle, and none of
    them reaches outside it -- which is what lets the folder be copied anywhere."""
    problems = []
    for source in [bundle.joinpath("index.html"), *sorted(bundle.rglob("*.css"))]:
        for reference in local_references(source.read_text(encoding="utf-8")):
            target = source.parent.joinpath(reference).resolve()
            where = source.relative_to(bundle)
            if bundle.resolve() not in target.parents:
                problems.append("%s reaches outside the bundle for %s" % (where, reference))
            elif not target.exists():
                problems.append("%s wants %s, which is not in the bundle" % (where, reference))
    assert not problems, "\n".join(problems)


def test_the_bundle_loads_nothing_from_a_4cat(bundle):
    """
    Nothing the page loads as part of itself may come from a 4CAT, an internal
    address, or anywhere else this bundle does not contain -- except the typefaces,
    which are loaded the way 4CAT itself loads them.

    Links a visitor can click are a different matter and are not checked here; the
    page is meant to link out to the 4CAT site and to the release it describes.
    """
    allowed = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
    for source in [bundle.joinpath("index.html"), *sorted(bundle.rglob("*.css")),
                   *sorted(bundle.rglob("*.js"))]:
        for reference in resources(source.read_text(encoding="utf-8")):
            if reference.startswith(("http://", "https://", "//")):
                assert reference.startswith(allowed), \
                    "%s loads %s" % (source.relative_to(bundle), reference)


def test_the_published_page_does_not_call_a_4cat_api(bundle):
    """
    The page tells the renderer to read the exported file instead of asking a 4CAT.

    The renderer still carries the live API address, because it is 4CAT's own file
    and that is what it falls back on inside the application -- so the check is that
    the page overrides it, not that the address is absent.
    """
    page = bundle.joinpath("index.html").read_text(encoding="utf-8")
    assert "/api/processor-map" not in page
    assert "MODULE_CATALOG_SOURCE" in page
    for source in sorted(bundle.rglob("*.css")):
        assert "/api/" not in source.read_text(encoding="utf-8")


def test_the_page_starts_from_the_manifest(bundle, export):
    """The page has no API to fall back on. It reads the manifest first and follows
    it to the data, rather than assuming a filename the export might change."""
    page = bundle.joinpath("index.html").read_text(encoding="utf-8")
    assert export.MANIFEST_FILE in page
    assert "MODULE_CATALOG_SOURCE" in page, "the page never says where to get its data"
    assert "manifest.data_file" in page, "the page does not follow the manifest to the data"


def test_the_renderer_is_4cats_own(bundle):
    """The published page runs the same JavaScript as 4CAT, rather than a copy."""
    published = bundle.joinpath("assets", "catalogue.js").read_bytes()
    assert published == PATH_ROOT.joinpath("webtool", "static", "js", "module-catalog.js").read_bytes()


# --- the finished bundle is read back before it counts as published --------

def test_the_page_and_the_export_must_agree_on_versions(export, bundle, tmp_path, monkeypatch):
    """The page states which versions it can read and the export checks its own
    output against that, so a bundle the published page cannot read is never
    written -- whichever of the two moved."""
    for attribute, expected in (("FORMAT_VERSION", "manifest version"), ("SCHEMA_VERSION", "data version")):
        copy = copy_of(bundle, tmp_path, attribute)
        monkeypatch.setattr(export, attribute, 99)
        with pytest.raises(RuntimeError, match=expected):
            export.check_bundle(copy)
        monkeypatch.undo()


def test_a_manifest_pointing_at_nothing_stops_the_export(export, bundle, tmp_path):
    copy = copy_of(bundle, tmp_path)
    rewrite_json(copy.joinpath("manifest.json"),
                 lambda data: data.update(data_file="data/not-here.json"))
    with pytest.raises(RuntimeError, match="not in the bundle"):
        export.check_bundle(copy)


def test_a_manifest_pointing_outside_the_bundle_stops_the_export(export, bundle, tmp_path):
    copy = copy_of(bundle, tmp_path)
    rewrite_json(copy.joinpath("manifest.json"),
                 lambda data: data.update(data_file="../somewhere-else.json"))
    with pytest.raises(RuntimeError, match="not inside the bundle"):
        export.check_bundle(copy)


def test_a_module_without_details_stops_the_export(export, bundle, tmp_path):
    copy = copy_of(bundle, tmp_path)
    rewrite_json(copy.joinpath("data", "catalogue-v1.json"),
                 lambda data: data["modules"].pop(data["catalogue"][0]["type"]))
    with pytest.raises(RuntimeError, match="listed but has no details"):
        export.check_bundle(copy)


def test_details_for_a_module_nobody_can_find_stops_the_export(export, bundle, tmp_path):
    copy = copy_of(bundle, tmp_path)
    rewrite_json(copy.joinpath("data", "catalogue-v1.json"),
                 lambda data: data["modules"].update({"not-in-the-catalogue": {"type": "x"}}))
    with pytest.raises(RuntimeError, match="not listed"):
        export.check_bundle(copy)


def test_a_module_listed_twice_stops_the_export(export, bundle, tmp_path):
    copy = copy_of(bundle, tmp_path)
    rewrite_json(copy.joinpath("data", "catalogue-v1.json"),
                 lambda data: data["catalogue"].append(dict(data["catalogue"][0])))
    with pytest.raises(RuntimeError, match="more than once"):
        export.check_bundle(copy)


def test_a_manifest_disagreeing_with_the_data_stops_the_export(export, bundle, tmp_path):
    copy = copy_of(bundle, tmp_path)
    rewrite_json(copy.joinpath("manifest.json"),
                 lambda data: data.update(source=dict(data["source"], git_commit="f" * 40)))
    with pytest.raises(RuntimeError, match="disagree about where this came from"):
        export.check_bundle(copy)


def test_template_syntax_reaching_the_finished_page_stops_the_export(export, bundle, tmp_path):
    """Belt and braces: the markup is checked before it is pasted in, and the
    finished page is checked again after."""
    copy = copy_of(bundle, tmp_path)
    page = copy.joinpath("index.html")
    page.write_text(page.read_text(encoding="utf-8") + "\n<p>{{ leftover }}</p>", encoding="utf-8")
    with pytest.raises(RuntimeError, match="nothing will fill in"):
        export.check_bundle(copy)


def test_a_file_missing_from_the_bundle_stops_the_export(export, bundle, tmp_path):
    copy = copy_of(bundle, tmp_path)
    copy.joinpath("assets", "css", "module-catalog.css").unlink()
    with pytest.raises(RuntimeError, match="not in the bundle"):
        export.check_bundle(copy)


def test_a_renderer_that_will_not_run_stops_the_export(export, bundle, tmp_path):
    copy = copy_of(bundle, tmp_path)
    copy.joinpath("assets", "catalogue.js").write_text("   \n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="empty"):
        export.check_bundle(copy)


# --- writing the output directory ------------------------------------------

def test_an_earlier_export_is_replaced(export, tmp_path):
    output = tmp_path.joinpath("bundle")
    output.mkdir()
    output.joinpath("manifest.json").write_text("{}", encoding="utf-8")
    output.joinpath("stale.json").write_text("from a previous release", encoding="utf-8")
    export.prepare_output(output)
    assert not output.joinpath("stale.json").exists()


def test_a_directory_that_is_not_an_export_is_left_alone(export, tmp_path):
    """Pointing the export at the wrong directory should not empty it."""
    output = tmp_path.joinpath("someones-work")
    output.mkdir()
    output.joinpath("notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(RuntimeError, match="left untouched"):
        export.prepare_output(output)
    assert output.joinpath("notes.txt").read_text(encoding="utf-8") == "keep me"
