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
    missing_modules = {}
    log_buffer = None
    config = None

    # settings names starting with one of these belong to 4CAT itself. A module
    # may not declare into them even where core does not use the name yet, so it
    # cannot claim a name a later 4CAT version might add and thereby own its
    # definition. Note `extensions.` is among them despite how it reads: those
    # are 4CAT's own settings *about* extensions.
    RESERVED_PREFIXES = ("privileges.", "flask.", "4cat.", "path.", "datasources.", "extensions.", "logging.")

    PROCESSOR = 1
    WORKER = 2

    workers = {}
    processors = {}
    datasources = {}

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
        # datasource's search or import worker class, which is in self.workers
        if write_cache:
            self.write_cache_file(config.get("PATH_CONFIG").joinpath("module_config.bin"),
                                  self.collect_module_config())

        # load from cache. If we just wrote it, insist it can be read back:
        # that turns a silently failed write into an error at boot, rather than
        # a back-end running on default values without saying so.
        self.config.load_user_settings(require_module_config=write_cache)

    def collect_module_config(self):
        """
        Collect the settings that modules declare

        Modules declare settings in a `config` dict on the worker class. Those
        are merged into one mapping here and cached for the config manager,
        which cannot read them itself: modules need the config manager in order
        to load, so loading them from it would be circular.

        A setting belongs to the first module that declares it, and some
        declarations are refused outright:

        - a name core already defines is refused. Core's definition is
          authoritative, and a module redefining it could change that setting's
          `type` (which decides how a saved value is validated), its `default`
          (used whenever nothing is stored) or its `global` flag (which decides
          whether values per user group apply at all).
        - a name in one of `RESERVED_PREFIXES` is refused even where core does
          not use it yet.
        - between two modules the first declarer wins - and 4CAT's own modules
          are visited before extensions, so an extension cannot take a name an
          in-tree module declares. Each group is visited in sorted order rather
          than the order the files happened to be found in, so which module wins
          does not depend on the machine.

        Every refusal is logged naming the module responsible. The setting is
        not registered and its declared definition is ignored.

        :return dict:  Setting name to definition
        """
        # imported here rather than at the top of the module: config_definition
        # pulls in user_input, and neither of them imports this module
        from common.lib.config_definition import config_definition as core_definition

        module_config = {}
        declared_by = {}

        # 4CAT's own modules first, then extensions, each alphabetically
        for worker_type in sorted(self.workers, key=lambda name:
                                  (bool(getattr(self.workers[name], "is_extension", False)), name)):
            worker_config = getattr(self.workers[worker_type], "config", None)
            if type(worker_config) is not dict:
                continue

            for setting, definition in worker_config.items():
                if type(definition) is not dict:
                    # everything downstream reads a definition as a mapping. It
                    # has to be caught here, while the module can still be
                    # named: whatever touches it first does so long afterwards.
                    refusal = "its definition is not a dictionary"
                elif setting in core_definition:
                    refusal = "it is already defined as a core 4CAT setting"
                elif setting.startswith(self.RESERVED_PREFIXES):
                    refusal = "it uses a name reserved for core 4CAT settings"
                elif setting in module_config:
                    if module_config[setting] is definition:
                        # the very same definition object, i.e. the setting is
                        # declared on a base class and this worker inherits it.
                        # Not a collision, and already registered.
                        continue

                    refusal = f"it was already declared by {declared_by[setting]}"
                else:
                    refusal = None

                if refusal:
                    self.log_buffer += (f"Setting '{setting}' declared by {worker_type} was refused: {refusal}. It "
                                        f"is not registered and its declared definition is ignored.\n")
                    continue

                module_config[setting] = definition
                declared_by[setting] = worker_type

        return module_config

    def write_cache_file(self, path, data):
        """
        Write the module settings cache

        Written to a temporary file and moved into place, so the front-end -
        which reads this file while the back-end writes it - sees either the
        previous version or the new one, never a half-written file.

        A definition can contain something that cannot be pickled; core itself
        keeps a lambda in one, so a module doing the same is plausible. Taking
        the back-end down at boot over one such setting would be out of
        proportion, so those settings are dropped from the cache and reported.

        :param Path path:  File to write
        :param dict data:  Settings to cache
        """
        try:
            payload = pickle.dumps(data)
        except Exception:
            # pickle raises PicklingError for some values and AttributeError or
            # TypeError for others, so this cannot be narrowed to one error
            unpicklable = []
            for key, value in data.items():
                try:
                    pickle.dumps({key: value})
                except Exception:
                    unpicklable.append(key)

            if not unpicklable:
                # every setting pickles on its own, so dropping one cannot fix
                # this and there is nothing useful to say about which
                raise

            self.log_buffer += (f"Could not cache these settings, so they will be unavailable: "
                                f"{', '.join(sorted(unpicklable))}. Their definitions contain something that "
                                f"cannot be pickled, e.g. a lambda.\n")

            data = {key: value for key, value in data.items() if key not in unpicklable}
            payload = pickle.dumps(data)

        # in the same folder, so the move below is a rename rather than a copy.
        # A fixed name rather than a unique one: only the back-end writes this,
        # and an interrupted write then leaves at most one stray file behind
        # instead of one per boot.
        temp_path = path.with_name(path.name + ".tmp")
        try:
            with temp_path.open("wb") as outfile:
                outfile.write(payload)

            os.replace(temp_path, path)
        except BaseException:
            # never leave a half-written temporary file behind
            temp_path.unlink(missing_ok=True)
            raise

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

        # 4CAT's own folders before the extensions folder: where an extension
        # and an in-tree module claim the same worker type, the in-tree one is
        # kept, rather than whichever the walk happened to reach first. An
        # extension's data source folder sits under the extensions folder, so
        # walking that covers it - listing it here as well would only mean
        # reaching the same classes twice.
        core_datasources = [self.datasources[datasource]["path"] for datasource in self.datasources
                            if extension_path not in self.datasources[datasource]["path"].parents]

        paths = [self.config.get('PATH_ROOT').joinpath("processors"),
                 self.config.get('PATH_ROOT').joinpath("backend/workers"),
                 *core_datasources,
                 extension_path]

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
                        key_name = e.name if hasattr(e, "name") else module_name
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
                            # already indexed
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

            if datasource_id in self.datasources:
                # 4CAT's own data sources are loaded before extensions, so this
                # keeps 4CAT's version rather than letting an extension replace
                # it - and with it the folder that load_modules() scans for that
                # data source's workers, which would take those workers and the
                # settings they declare out of 4CAT altogether.
                self.log_buffer += ("Data source '%s' in %s is already provided by %s, so it is not loaded. Give one "
                                    "of them a different DATASOURCE id.\n" %
                                    (datasource_id, subdirectory, self.datasources[datasource_id]["path"]))
                return

            self.datasources[datasource_id] = {
                "expire-datasets": expiration.get(datasource_id, None),
                "path": subdirectory,
                "name": datasource.NAME if hasattr(datasource, "NAME") else datasource_id,
                "id": subdirectory.parts[-1],
                "init": datasource.init_datasource,
                "config": {} if not hasattr(datasource, "config") else datasource.config,
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