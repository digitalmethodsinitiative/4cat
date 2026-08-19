"""
Load modules and datasources dynamically
"""
from pathlib import Path
import importlib
import inspect
import pickle
import sys
import re
import os


class ModuleCollector:
    """
    Collects all modular appendages of 4CAT

    On init, an object of this class collects all datasources and workers that
    have been added to this 4CAT installation. The metadata of these is then
    stored for later access.

    Datasources are found in the "datasources" folder in root. Workers are
    found in datasource folders or the default "processors" and
    "backend/workers" folder. All these folders are scanned for both
    processors and workers (processors being a specific kind of worker).

    A process is expected to build one collector only. The registries below are
    class attributes, so what one collector finds stays visible to any collector
    built later in the same process, and that later collector skips every module
    the first one already indexed. Also note that the file path and extension flag 
    are also stored on the worker classes themselves, which Python shares 
    process-wide through its module cache.
    """
    ignore = []
    # missing dependency -> the modules that needed it, which is the grouping the
    # "install these packages" warning at the end of load_modules() wants
    missing_modules = {}
    # name -> why it could not be seen. Everything in here means some settings
    # went undeclared while whatever owns them is installed and still reads them.
    scan_failures = {}
    log_buffer = None
    config = None

    PROCESSOR = 1
    WORKER = 2

    workers = {}
    processors = {}
    datasources = {}

    # Namespaces reserved for core settings. A module-declared setting may never
    # enter these, so an extension cannot squat a name 4CAT might add later and
    # thereby own its definition (which controls `global`, `default` and `type`).
    RESERVED_PREFIXES = ("privileges.", "flask.", "4cat.", "path.", "datasources.", "extensions.", "logging.")

    def __init__(self, config, write_cache=False):
        """
        Load data sources and workers

        Datasources are loaded first so that the datasource folders may be
        scanned for workers subsequently.

        :param config:  Configuration manager, shared with the rest of the
        context
        :param bool write_cache:  Write modules to cache file?
        """
        # this can be flushed later once the logger is available
        self.log_buffer = ""
        self.config = config

        self.load_datasources()
        self.load_modules()

        # now we know all workers, we can add some extra metadata to the
        # datasources, e.g. whether they have an associated search worker
        self.expand_datasources()

        # cache module-defined config options for use by the config manager
        # this covers datasource settings too: those are declared on the
        # datasource's search/import worker class, which is in self.workers
        if write_cache:
            module_config, provenance, collisions = self.collect_module_config()
            config_path = config.get("PATH_CONFIG")

            # two files, deliberately. module_config.bin's shape is merged
            # straight into the config definition by every reader, including a
            # front-end container that may still be running older code, so it
            # is frozen as a plain {name: definition} mapping. Everything new
            # goes in the sidecar, which has no legacy readers and can carry a
            # format version. Do not merge these back together: that would put
            # the combined shape back on the load-bearing path.
            self.write_cache_file(config_path.joinpath("module_config.bin"), module_config,
                                  drop_unpicklable=True)
            self.write_cache_file(config_path.joinpath("module_config_provenance.bin"), {
                "format": 1,
                "provenance": provenance,
                "collisions": collisions
            })

        # load from cache. If we just wrote it, insist it can be read back -
        # that turns a silently failed write into an error at boot rather than
        # a back-end running on default values.
        self.config.load_user_settings(require_module_config=write_cache)

    def collection_failures(self):
        """
        Everything that stopped this collection from seeing all of 4CAT

        Anything listed here means some settings went undeclared this boot even
        though whatever owns them is installed and still reads them. That has to
        keep the declaration scan from counting as complete, or those settings
        age into looking obsolete while they are merely out of reach.

        Ask here rather than adding up the registries at the call site, so a
        newly-found way to lose part of 4CAT has one place to register itself.

        :return dict:  Description by module or setting name, empty if all well
        """
        return {
            # flipped: missing_modules groups by dependency, but a caller counting
            # what was lost needs one entry per module
            **{module: f"could not be imported (missing dependency: {dependency})"
               for dependency, modules in self.missing_modules.items() for module in modules},
            **self.scan_failures
        }

    def collect_module_config(self):
        """
        Collect module-declared settings, with provenance and collisions

        Modules declare settings in a `config` dict on the worker class.

        Collisions are refused rather than merged, on three rules:

        - a key already defined in core `config_definition` is refused. The core
          definition is authoritative; a module overriding it can change that
          setting's `global` flag (which collapses per-tag resolution), its
          `default` (reachable whenever no row exists) or its `type` (which
          weakens validation).
        - a key in a namespace reserved for core is refused outright, even if
          core does not define it yet.
        - between two modules, the first declarer wins. Workers are visited in
          sorted order rather than filesystem order so this is reproducible
          across machines.

        :return tuple:  `(module_config, provenance, collisions)`
        """
        # safe to import here: config_definition pulls in user_input, neither of
        # which imports this module
        from common.lib.config_definition import config_definition as core_definition, submenus

        module_config = {}
        provenance = {}
        collisions = []

        for worker_type in sorted(self.workers):
            worker = self.workers[worker_type]
            worker_config = getattr(worker, "config", None)
            if type(worker_config) is not dict:
                continue

            is_extension = bool(getattr(worker, "is_extension", False))
            extension_id = getattr(worker, "extension_name", None) if is_extension else None

            for setting, definition in worker_config.items():
                if type(definition) is not dict:
                    # everything downstream reads a definition as a mapping. Has
                    # to be caught here, where the module can still be named: the
                    # first thing to touch it is record_declarations() at boot,
                    # which runs before the log buffer is flushed, so the
                    # AttributeError would arrive with nothing pointing at the
                    # module that caused it.
                    refusal = "its definition is not a dictionary"
                elif setting in core_definition:
                    refusal = "it is already defined as a core setting"
                elif setting.startswith(self.RESERVED_PREFIXES):
                    refusal = "it uses a namespace reserved for core settings"
                elif setting in module_config:
                    if module_config[setting] is definition:
                        # the very same definition object, i.e. the setting is
                        # declared on a base class and this worker inherits it.
                        # not a collision - just note the extra declarer.
                        provenance[setting]["also_declared_by"].append(worker_type)
                        continue

                    refusal = f"it was already declared by {provenance[setting]['declared_by']}"
                else:
                    refusal = None

                if refusal:
                    collisions.append({
                        "setting": setting,
                        "declared_by": worker_type,
                        "extension_id": extension_id,
                        "reason": refusal
                    })
                    # the worker still reads this setting, but it is no longer in
                    # the definition, so the scan is not complete
                    reason = f"declared by {worker_type} but refused: {refusal}"
                    self.scan_failures[setting] = reason
                    self.log_buffer += (f"Setting '{setting}' {reason}. It is not registered and its declared "
                                        f"definition is ignored.\n")
                    continue

                # not a refusal - the setting is fine, only its placement is
                # nonsense, and losing a working setting over a typo in an
                # optional presentation key would be out of proportion. The
                # settings panel falls back to working the tab out itself, so
                # say so here or the author gets no signal at all.
                if definition.get("submenu") not in (None, *submenus):
                    self.log_buffer += (f"Setting '{setting}' declared by {worker_type} asks for submenu "
                                        f"'{definition['submenu']}', which is not one of {', '.join(submenus)}. The "
                                        f"setting is registered, but its tab will be placed automatically.\n")

                module_config[setting] = definition
                provenance[setting] = {
                    "declared_by": worker_type,
                    "kind": "extension" if is_extension else "core",
                    "extension_id": extension_id,
                    # other workers inheriting the same definition; the setting
                    # is live as long as any one of them loads
                    "also_declared_by": []
                }

        return module_config, provenance, collisions

    def write_cache_file(self, path, data, drop_unpicklable=False):
        """
        Pickle data to a file, atomically

        Written to a temporary file and moved into place, so a reader in the
        other container never sees a half-written file.

        :param Path path:  File to write
        :param data:  Picklable data
        :param bool drop_unpicklable:  For the settings cache only. A module can
        declare a setting whose definition cannot be pickled - core itself puts
        a lambda in one definition, so an extension doing the same is plausible.
        Rather than take the back-end down at boot, those settings are dropped,
        reported, and recorded in `scan_failures` so the boot counts as
        incomplete: they are missing from the definition while the module that
        declares them is loaded and still reading them, which is exactly the
        state that must not be mistaken for a setting having been removed.
        Never pass this for the provenance sidecar, where dropping a key would
        silently discard the whole provenance map.
        """
        try:
            payload = pickle.dumps(data)
        except Exception:
            if not drop_unpicklable or type(data) is not dict:
                raise

            # find the culprits so the log can name them, instead of failing
            # with a traceback that points only at this line
            unpicklable = []
            for key, value in data.items():
                try:
                    pickle.dumps({key: value})
                except Exception:
                    unpicklable.append(key)

            if not unpicklable:
                raise

            self.log_buffer += (f"Could not cache these settings, they will be unavailable: "
                                f"{', '.join(sorted(unpicklable))}. Their definitions contain something that "
                                f"cannot be pickled (e.g. a lambda).\n")
            self.scan_failures.update({key: f"definition could not be pickled, so it is missing from {path.name}"
                                       for key in unpicklable})
            data = {key: value for key, value in data.items() if key not in unpicklable}
            payload = pickle.dumps(data)

        temp_path = path.with_name(path.name + ".tmp")
        with temp_path.open("wb") as outfile:
            outfile.write(payload)

        os.replace(temp_path, path)

    @staticmethod
    def is_4cat_class(object, only_processors=False):
        """
        Determine if a module member is a worker class we can use
        """
        if inspect.isclass(object):
            if object.__name__ in("BasicProcessor", "BasicWorker") or inspect.isabstract(object):
                # ignore abstract and base classes
                return False

            if hasattr(object, "is_4cat_class"):
                if only_processors:
                    if hasattr(object, "is_4cat_processor"):
                        return object.is_4cat_processor()
                    else:
                        return False
                else:
                    return object.is_4cat_class()

        return False

    def load_modules(self):
        """
        Load modules

        Modules are workers and (as a subset of workers) postprocessors. These
        are found by importing any python files found in the given locations,
        and looking for relevant classes within those python files, that extend
        `BasicProcessor` or `BasicWorker` and are not abstract.
        """
        # look for workers and processors in pre-defined folders and datasources

        extension_path = self.config.get('PATH_EXTENSIONS')
        enabled_extensions = [e for e, s in self.config.get("extensions.enabled").items() if s["enabled"]]

        paths = [self.config.get('PATH_ROOT').joinpath("processors"),
                 self.config.get('PATH_ROOT').joinpath("backend/workers"),
                 extension_path,
                 *[self.datasources[datasource]["path"] for datasource in self.datasources]] # extension datasources will be here and the above line...

        root_match = re.compile(r"^%s" % re.escape(str(self.config.get('PATH_ROOT'))))
        root_path = self.config.get('PATH_ROOT')

        for folder in paths:
            # loop through folders, and files in those folders, recursively
            is_extension = extension_path in folder.parents or folder == extension_path
            for root, dirs, files in os.walk(folder, followlinks=True):
                for filename in files:
                    if not filename.endswith('.py'):
                        continue

                    file = Path(root) / filename

                    # determine module name for file
                    # reduce path to be relative to 4CAT root
                    module_name = ".".join(file.parts[len(root_path.parts):-1] + (file.stem,))
                    extension_name = file.parts[len(extension_path.parts):][0] if is_extension else None

                    # check if we've already loaded this module
                    if module_name in self.ignore:
                        continue

                    if is_extension and len(module_name.split(".")) > 1 and extension_name not in enabled_extensions:
                        continue

                    # try importing
                    try:
                        module = importlib.import_module(module_name)
                    except (SyntaxError, ImportError) as e:
                        # this is fine, just ignore this data source and give a heads up
                        self.ignore.append(module_name)
                        # a hand-raised ImportError("install x") has .name set to None,
                        # which would key this dict by None and later break sorting it
                        key_name = getattr(e, "name", None) or module_name
                        if key_name not in self.missing_modules:
                            self.missing_modules[key_name] = [module_name]
                        else:
                            self.missing_modules[key_name].append(module_name)
                        continue

                    # see if module contains the right type of content by looping
                    # through all of its members
                    components = inspect.getmembers(module, predicate=self.is_4cat_class)
                    for component in components:
                        if component[1].__module__ != module_name:
                            # this is not the module we're looking for (e.g. a base class imported from elsewhere), skip it
                            continue

                        if component[1].type in self.workers:
                            # paths lists some folders twice - an extension data source
                            # is under both the extension folder and its own path - so
                            # the same class is reached more than once, which is fine.
                            # Two *different* classes claiming one type is a naming bug.
                            if self.workers[component[1].type] is not component[1]:
                                self.log_buffer += (
                                    f"Worker type '{component[1].type}' is declared by two classes: "
                                    f"{self.workers[component[1].type].__module__} and {module_name}. Only the "
                                    f"first is loaded; give one of them a different type.\n")
                            continue

                        # extract data that is useful for the scheduler and other
                        # parts of 4CAT
                        relative_path = root_match.sub("", str(file))

                        self.workers[component[1].type] = component[1]
                        self.workers[component[1].type].filepath = relative_path
                        self.workers[component[1].type].is_extension = is_extension
                        if is_extension:
                            self.workers[component[1].type].extension_name = extension_name

                        # we can't use issubclass() because for that we would need
                        # to import BasicProcessor, which would lead to a circular
                        # import
                        if self.is_4cat_class(component[1], only_processors=True):
                            self.processors[component[1].type] = self.workers[component[1].type]

        # sort by category for more convenient display in interfaces
        sorted_processors = {id: self.processors[id] for id in
                             sorted(self.processors)}

        categorised_processors = {id: sorted_processors[id] for id in
                                  sorted(sorted_processors,
                                         key=lambda item: "0" if sorted_processors[item].category == "Presets" else
                                         sorted_processors[item].category)}

        # Give a heads-up if not all modules were installed properly
        if self.missing_modules:
            warning = "Warning: Not all modules could be found, which might cause data sources and modules to not " \
                      "function.\nMissing modules:\n"
            for missing_module, processor_list in self.missing_modules.items():
                warning += "\t%s (for %s)\n" % (missing_module, ", ".join(processor_list))

            self.log_buffer += warning

        self.processors = categorised_processors

    def load_datasources(self):
        """
        Load datasources

        This looks for folders within the datasource root folder that contain
        an `__init__.py` defining an `init_datasource` function and a
        `DATASOURCE` constant. The latter is taken as the ID for this
        datasource.
        """
        def _load_datasource(subdirectory, expiration):
            """
            Load a single datasource
            """
            # determine module name (path relative to 4CAT root w/ periods)
            module_name = ".".join(subdirectory.relative_to(self.config.get("PATH_ROOT")).parts)
            try:
                datasource = importlib.import_module(module_name)
            except ImportError as e:
                # its workers are never found either, so its settings go undeclared
                self.scan_failures[module_name] = f"data source could not be imported: {e}"
                self.log_buffer += "Could not import %s: %s\n" % (module_name, e)
                return

            if getattr(datasource, "DATASOURCE_DISABLED", False):
                # module deliberately declined to register (e.g. dev-only datasource
                # gated behind an env var); not an error, so don't warn.
                return

            if not hasattr(datasource, "init_datasource") or not hasattr(datasource, "DATASOURCE"):
                self.log_buffer += "Could not load datasource %s: missing init_datasource or DATASOURCE\n" % subdirectory
                return

            datasource_id = datasource.DATASOURCE

            self.datasources[datasource_id] = {
                "expire-datasets": expiration.get(datasource_id, None),
                "path": subdirectory,
                "name": datasource.NAME if hasattr(datasource, "NAME") else datasource_id,
                "id": subdirectory.parts[-1],
                "init": datasource.init_datasource,
                "explorer-templates": self.load_datasource_explorer_templates(datasource_id, subdirectory)
            }

        # Load 4CAT core datasources
        expiration = self.config.get("datasources.expiration", {})
        for subdirectory in self.config.get('PATH_ROOT').joinpath("datasources").iterdir():
            if subdirectory.is_dir():
                _load_datasource(subdirectory, expiration)

        # Load extension datasources
        # os.walk is used to allow for the possibility of multiple extensions, with nested "datasources" folders
        enabled_extensions = [e for e, s in self.config.get("extensions.enabled").items() if s["enabled"]]
        extensions_root = self.config.get('PATH_EXTENSIONS')
        for root, dirs, files in os.walk(extensions_root, followlinks=True):
            relative_root = Path(root).relative_to(extensions_root)
            if relative_root.parts and relative_root.parts[0] not in enabled_extensions:
                continue

            if "datasources" in dirs:
                for subdirectory in Path(root, "datasources").iterdir():
                    if subdirectory.is_dir():
                        _load_datasource(subdirectory, expiration)

        sorted_datasources = {datasource_id: self.datasources[datasource_id] for datasource_id in
                              sorted(self.datasources, key=lambda id: self.datasources[id]["name"])}
        self.datasources = sorted_datasources

    def get_datasource_worker(self, datasource_id):
        """
        Find the collector or importer worker for a datasource

        A datasource is served by a single worker that collects or imports its
        items. By convention that worker's type is the datasource ID followed
        by `-search` (a collector, e.g. `tiktok-search`) or `-import` (an
        importer, e.g. `twitter-import`). Both suffixes are tried, `-search`
        first.

        :param str datasource_id:  Datasource ID, e.g. `twitter`
        :return:  The worker class for the datasource, or None if it has none
        """
        for suffix in ("-search", "-import"):
            worker = self.workers.get(datasource_id + suffix)
            if worker:
                return worker
        return None

    def expand_datasources(self):
        """
        Expand datasource metadata

        Some datasource metadata can only be known after all workers have been
        loaded, e.g. whether there is a search or import worker for the
        datasource. This function takes care of populating those values.
        """
        for datasource_id in self.datasources:
            worker = self.get_datasource_worker(datasource_id)
            self.datasources[datasource_id]["has_worker"] = bool(worker)
            self.datasources[datasource_id]["has_options"] = bool(worker) and \
                                                             bool(worker.get_options(config=self.config))
            self.datasources[datasource_id]["importable"] = worker and hasattr(worker, "is_from_zeeschuimer") and worker.is_from_zeeschuimer

    def load_datasource_explorer_templates(self, datasource_id, datasource_path):
        """
        Find CSS and HTML template file paths for a datasource
        
        Looks for templates in multiple locations:
        - Within the datasource folder itself
        - In config/extensions/ (for extensions)
        
        :param datasource_id: The datasource identifier
        :param datasource_path: Path to the datasource folder
        :return: Dictionary with 'css' and 'html' keys containing template file paths
        """
        templates = {"css": None, "html": None}
        
        # Look for CSS template
        css_filename = f"{datasource_id}-explorer.css"
        
        # Check within datasource folder
        datasource_css = datasource_path / css_filename
        if datasource_css.exists():
            templates["css"] = datasource_css
        
        # Check extensions folder
        if not templates["css"]:
            extensions_path = self.config.get('PATH_EXTENSIONS')
            if extensions_path.exists():
                for root, dirs, files in os.walk(extensions_path, followlinks=True):
                    if css_filename in files:
                        templates["css"] = Path(root) / css_filename
                        break
        
        # Look for HTML template
        html_filename = f"{datasource_id}-explorer.html"
        
        # Check within datasource folder
        datasource_html = datasource_path / html_filename
        if datasource_html.exists():
            templates["html"] = datasource_html
            return templates

        # Check extensions folder
        if not templates["html"]:
            extensions_path = self.config.get('PATH_EXTENSIONS')
            if extensions_path.exists():
                for root, dirs, files in os.walk(extensions_path, followlinks=True):
                    if html_filename in files:
                        templates["html"] = Path(root) / html_filename
                        break
        
        return templates

    def load_worker_class(self, worker):
        """
        Get class for worker

        This import worker modules on-demand, so the code is only loaded if a
        worker that needs the code is actually queued and run

        :return:  Worker class for the given worker metadata
        """
        module = worker["module"]
        if module not in sys.modules:
            importlib.import_module(module)

        return getattr(sys.modules[module], worker["class_name"])