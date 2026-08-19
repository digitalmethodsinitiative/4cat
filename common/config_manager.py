import itertools
import threading
import pickle
import time
import json

from pymemcache.client.base import Client as MemcacheClient
from pymemcache.exceptions import MemcacheError
from pymemcache import serde
from pathlib import Path
from common.lib.database import Database

from common.lib.exceptions import ConfigException
from common.lib.config_definition import config_definition

import configparser
import os

class CacheMiss:
    """
    Helper class to distinguish memcache misses from true `None` values
    """
    pass

class BaseConfigReader:
    """
    Helper class to unify various types of configuration readers
    """
    pass

class ConfigManager(BaseConfigReader):
    db = None
    dbconn = None
    cache = {}
    logger = None

    core_settings = {}
    config_definition = {}
    # who declared each module-defined setting, and any declarations refused for
    # colliding with core or with another module. Populated from the sidecar
    # cache file; empty on an instance whose back-end has not written one yet.
    setting_provenance = {}
    setting_collisions = []
    # how long a setting must go undeclared, across complete scans, before the
    # audit will call it removed rather than merely unseen
    ORPHAN_GRACE_PERIOD = 7 * 86400

    # why a setting in each of the other audit states is not archivable
    ARCHIVE_REFUSALS = {
        "dormant": "it belongs to an extension that is installed, so switching that extension back on should restore "
                   "its configuration.",
        "absent_extension": "it belongs to an extension that is not installed. Re-installing it should restore its "
                            "configuration rather than reverting to defaults.",
        "recently_absent": "it has not been undeclared for long enough to be sure it is gone rather than in the middle "
                           "of being moved. It may also be that the last start-up could not load every module.",
        "unknown": "4CAT has no record of anything declaring it. That is not evidence it was removed - it may "
                   "belong to an extension that was already uninstalled or switched off before 4CAT began keeping "
                   "track. It is kept for that reason."
    }
    # Thread-local storage for a singleton memcache client per thread.
    # Prevents creating a new TCP connection per request in threaded/gunicorn contexts.
    _memcache_tls = threading.local()

    def __init__(self, db=None, require_module_config=False):
        """
        :param db:  Database object
        :param bool require_module_config:  Refuse to initialise if
        module-defined settings are unavailable. See `load_user_settings()`.
        """
        # ensure core settings (including database config) are loaded
        self.load_core_settings()
        self.load_user_settings(require_module_config=require_module_config)
        # Do not create a memcache client here; get_memcache() will lazily create per-thread.

        # establish database connection if none available
        if db:
            self.with_db(db)

    def with_db(self, db=None):
        """
        Initialise database

        Not done on init, because something may need core settings before the
        database can be initialised

        :param db:  Database object. If None, initialise it using the core config
        """
        if db or not self.db:
            if db and db.log and not self.logger:
                # borrow logger from database
                self.with_logger(db.log)

            # Replace w/ db if provided else only initialise if not already
            self.db = db if db else Database(logger=self.logger, dbname=self.get("DB_NAME"), user=self.get("DB_USER"),
                                         password=self.get("DB_PASSWORD"), host=self.get("DB_HOST"),
                                         port=self.get("DB_PORT"), appname="config-reader")
        else:
            # self.db already initialized and no db provided
            pass

    def with_logger(self, logger):
        """
        Attach logger to config manager

        4CAT's logger has some features on top of the basic Python logger that
        are needed for further operation, e.g. the Debug2 log level.

        :param Logger logger:
        """
        self.logger = logger

    def load_user_settings(self, require_module_config=False):
        """
        Load settings configurable by the user

        Does not load the settings themselves, but rather the definition so
        values can be validated, etc

        Without the module definitions, module-defined settings have no `type`,
        no `default` and no `global` flag. Stored values are not at risk:
        `UserInput.parse_all()` only returns keys that are in the definition it
        is handed, and the settings form is saved from that, so a setting
        missing from the definition cannot be written over. What breaks is the
        control panel, which would then silently offer a fraction of 4CAT's
        settings, and a `global` setting would resolve per tag. That is why a
        serving front-end refuses to start without them.

        The back-end cannot make the same demand: it *writes* the cache, so on a
        first boot it necessarily starts without one. Neither can `migrate.py`,
        `docker_setup` or the helper scripts, which all run before the back-end
        has ever booted. Those pass `require_module_config=False` (the default).

        :param bool require_module_config:  Raise if module-defined settings
        could not be loaded, instead of continuing with core settings only
        """
        # basic 4CAT settings
        self.config_definition.update(config_definition)

        # module settings can't be loaded directly because modules need the
        # config manager to load, so that becomes circular
        # instead, this is cached on startup and then loaded here
        config_path = self.get("PATH_CONFIG")

        module_config_path = config_path.joinpath("module_config.bin")
        module_config = self.load_cache_file(module_config_path)
        if module_config is not None:
            # note: an empty mapping is valid (no module declares a setting) and
            # is not the same as a failed read
            self.config_definition.update(module_config)
        elif require_module_config:
            if module_config_path.exists():
                raise ConfigException(f"{module_config_path.name} exists but could not be read. Refusing to start: "
                                      f"every module-defined setting would be missing from the control panel, which "
                                      f"would then quietly show an incomplete picture of how 4CAT is configured.")

            raise ConfigException(f"No {module_config_path.name} file exists! It is written by the back-end when it "
                                  f"boots, so the back-end must be started first.")

        # provenance (which module declared which setting) lives in a separate
        # file on purpose - see ModuleCollector.__init__ for why they are not
        # one file. Absent on an instance that has not yet booted a back-end
        # with this code, in which case every setting is simply unattributed.
        sidecar = self.load_cache_file(config_path.joinpath("module_config_provenance.bin"))
        if type(sidecar) is dict and sidecar.get("format") == 1:
            self.setting_provenance = sidecar.get("provenance", {})
            self.setting_collisions = sidecar.get("collisions", [])

    def load_cache_file(self, path):
        """
        Read one of the module config cache files

        If 4CAT runs as two containers (front-end and back-end) both may read
        this while the back-end writes it. Writes are atomic, so a reader sees
        either the old file or the new one - but a file being replaced can still
        briefly fail to open, so a couple of retries are allowed.

        Note the file must be reopened for each attempt: a failed `pickle.load`
        leaves the handle partway through the stream, so retrying on the same
        handle can never succeed.

        :param Path path:  File to read
        :return:  Unpickled contents, or `None` if unreadable
        """
        if not path.exists():
            return None

        for _ in range(3):
            try:
                with path.open("rb") as infile:
                    return pickle.load(infile)
            except Exception:  # a number of exceptions, all with the same recovery path
                time.sleep(0.1)

        # whether this is fatal is the caller's decision - see
        # load_user_settings(require_module_config=...)
        if self.logger:
            self.logger.warning(f"Could not read {path.name} - module-defined settings are unavailable until the "
                                f"back-end writes it again.")

        return None

    def load_core_settings(self):
        """
        Load 4CAT core settings

        These are (mostly) stored in config.ini and cannot be changed from the
        web interface.

        :return:
        """
        config_file = Path(__file__).parent.parent.joinpath("config/config.ini")
        config_reader = configparser.ConfigParser()
        in_docker = False
        if config_file.exists():
            config_reader.read(config_file)
            if config_reader["DOCKER"].getboolean("use_docker_config"):
                # Can use throughtout 4CAT to know if Docker environment
                in_docker = True
        else:
            # config should be created!
            raise ConfigException("No config/config.ini file exists! Update and rename the config.ini-example file.")
        
        # Set up core settings
        # Using Path.joinpath() will ensure paths are relative to ROOT_PATH or absolute (if /some/path is provided)
        root_path = Path(os.path.abspath(os.path.dirname(__file__))).joinpath("..").resolve() # better don"t change this

        self.core_settings.update({
            "CONFIG_FILE": config_file.resolve(),
            "USING_DOCKER": in_docker,
            "DB_HOST": config_reader["DATABASE"].get("db_host"),
            "DB_PORT": config_reader["DATABASE"].get("db_port"),
            "DB_USER": config_reader["DATABASE"].get("db_user"),
            "DB_NAME": config_reader["DATABASE"].get("db_name"),
            "DB_PASSWORD": config_reader["DATABASE"].get("db_password"),

            "API_HOST": config_reader["API"].get("api_host"),
            "API_PORT": config_reader["API"].getint("api_port"),

            "MEMCACHE_SERVER": config_reader.get("MEMCACHE", option="memcache_host", fallback=None),

            "PATH_ROOT": root_path,
            "PATH_CONFIG": root_path.joinpath("config"), # .current-version, config.ini are hardcoded here via docker/docker_setup.py and helper-scripts/migrate.py
            "PATH_EXTENSIONS": root_path.joinpath("config/extensions"), # Must match setup.py and migrate.py
            "PATH_LOGS": root_path.joinpath(config_reader["PATHS"].get("path_logs", "")),
            "PATH_IMAGES": root_path.joinpath(config_reader["PATHS"].get("path_images", "")),
            "PATH_DATA": root_path.joinpath(config_reader["PATHS"].get("path_data", "")),
            "PATH_LOCKFILE": root_path.joinpath(config_reader["PATHS"].get("path_lockfile", "")),
            "PATH_SESSIONS": root_path.joinpath(config_reader["PATHS"].get("path_sessions", "")),

            "ANONYMISATION_SALT": config_reader["GENERATE"].get("anonymisation_salt"),
            "SECRET_KEY": config_reader["GENERATE"].get("secret_key")
        })


    def get_memcache(self):
        """
        Get (or create) a thread-local memcache client

        The config reader can optionally use Memcache to keep fetched values in
        memory.
        """
        # Reuse per-thread client if already initialised.
        existing = getattr(self._memcache_tls, "client", None)
        if existing:
            return existing

        server = self.get("MEMCACHE_SERVER")
        if server:
            try:
                memcache = MemcacheClient(server, serde=serde.pickle_serde, key_prefix=b"4cat-config")
                # do one test fetch to test if connection is valid
                memcache.set("4cat-init-dummy", time.time())
                memcache.init_thread_id = threading.get_ident()
                self._memcache_tls.client = memcache
                return memcache
            except (SystemError, ValueError, MemcacheError, ConnectionError, OSError):
                # we have no access to the logger here so we simply pass
                # later we can detect elsewhere that a memcache address is
                # configured but no connection is there - then we can log
                # config reader still works without memcache
                pass

        return None

    def close_memcache(self):
        """Close and dispose this thread's memcache client.

        Call from gunicorn worker_exit or application teardown to ensure
        sockets are closed explicitly instead of relying on GC/process exit.
        """
        client = getattr(self._memcache_tls, "client", None)
        if client:
            try:
                client.close()
            except Exception:
                pass
            finally:
                try:
                    del self._memcache_tls.client
                except AttributeError:
                    pass
        

    def ensure_database(self):
        """
        Ensure the database is in sync with the config definition

        Creates a global setting with the default value for every setting in
        the config definition that has no value in the database yet, and keeps
        the tag order in sync with the tags actually in use.

        This does *not* delete settings that are in the database but no longer
        defined anywhere to avoid deleting settings because their
        extension is uninstalled or disabled, or because their module failed to
        import this boot; telling those apart needs provenance that is not
        available here.

        Note this runs *before* the ModuleCollector (see backend/bootstrap.py),
        which reads `extensions.enabled` and `datasources.expiration` from the
        database. It therefore sees the module config cached by the *previous*
        boot, and on a fresh install sees no module-declared settings at all -
        those first get a row on the second boot.
        """
        self.with_db()

        # create global values for known keys with the default
        known_settings = self.get_all_setting_names()
        for setting, parameters in self.config_definition.items():
            if setting in known_settings:
                continue

            self.db.log.debug(f"Creating setting: {setting} with default value {parameters.get('default', '')}")
            self.set(setting, parameters.get("default", ""))

        # make sure settings and user table are in sync
        user_tags = list(set(itertools.chain(*[u["tags"] for u in self.db.fetchall("SELECT DISTINCT tags FROM users")])))
        known_tags = [t["tag"] for t in self.db.fetchall("SELECT DISTINCT tag FROM settings")]
        tag_order = self.get("flask.tag_order")

        for tag in known_tags:
            # add tags used by a setting to tag order
            if tag and tag not in tag_order:
                tag_order.append(tag)

        for tag in user_tags:
            # add tags used by a user to tag order
            if tag and tag not in tag_order:
                tag_order.append(tag)

        # admin tag should always be first in order
        if "admin" in tag_order:
            tag_order.remove("admin")

        tag_order.insert(0, "admin")

        self.set("flask.tag_order", tag_order)
        self.db.commit()

    def record_declarations(self, degraded=False):
        """
        Record which module declares each setting, and when it was last seen

        Run after the ModuleCollector, since it needs the provenance the
        collector works out while loading modules. Every setting declared this
        boot gets a row: module-declared ones are attributed to the worker that
        declared them, core ones to `config_definition`.

        Only settings that really were declared this boot are recorded.
        `config_definition` is merged rather than rebuilt, so it can still hold
        a setting from the *previous* boot's module cache - the boot right after
        an extension is switched off is exactly that case, since the sidecar is
        replaced wholesale but the definition is not. Recording those would
        attribute them to core, wiping out the extension they belong to, and
        they would end up offered for removal while the extension is merely off.

        A setting in the `settings` table with *no* row here is one that nothing
        currently declares. That alone is not grounds to remove it - it may
        belong to an extension that is uninstalled or disabled - which is why
        this only ever writes rows and never deletes them.

        :param bool degraded:  True if some modules failed to import this boot.
        Declarations are still recorded (what loaded really was seen), but the
        clean-scan marker is not advanced, so nothing can age into looking
        obsolete while an import is broken.
        :return int:  Number of declarations recorded
        """
        self.with_db()
        now = int(time.time())

        declarations = []
        for setting, definition in self.config_definition.items():
            declared = self.setting_provenance.get(setting)
            if declared is None and setting not in config_definition:
                # left over from the previous boot's module cache, not declared
                # by anything now. Leave whatever was recorded for it alone.
                continue

            declared = declared or {}

            try:
                # definitions can hold values JSON cannot represent (core has a
                # lambda in one), and this is only ever read back for display
                last_definition = json.dumps(definition, default=str)
            except (TypeError, ValueError):
                last_definition = None

            declarations.append((
                setting,
                declared.get("declared_by", "core:config_definition"),
                declared.get("kind", "core"),
                declared.get("extension_id"),
                bool(definition.get("indirect", False)),
                now,
                now,
                last_definition
            ))

        if declarations:
            # note first_seen is deliberately absent from the update list: it
            # records when a setting was first known, so it must survive
            self.db.execute_many("""
                INSERT INTO settings_declarations
                    (name, declared_by, owner_kind, extension_id, is_indirect,
                     first_seen, last_seen, last_definition)
                VALUES %s
                ON CONFLICT (name) DO UPDATE SET
                    declared_by = EXCLUDED.declared_by,
                    owner_kind = EXCLUDED.owner_kind,
                    extension_id = EXCLUDED.extension_id,
                    is_indirect = EXCLUDED.is_indirect,
                    last_seen = EXCLUDED.last_seen,
                    last_definition = EXCLUDED.last_definition,
                    -- declared again, so whatever absence was recorded is over
                    absent_since = NULL
            """, replacements=declarations, commit=False)

        # written on every boot, unlike the clean-scan marker below: this is what
        # tells the audit whether the most recent start-up could see everything
        self.set("4cat.declarations_last_scan_complete", not degraded)

        if not degraded:
            # anything with a row that was not declared this boot starts its
            # clock now, which is the moment we actually saw it missing.
            # Measuring from last_seen instead counts the previous run's uptime
            # as time spent absent, so a setting dropped by an upgrade on a
            # server that had been up a month looks a month gone the instant it
            # goes. Only on a complete boot: while an import is broken we cannot
            # tell missing from unreachable.
            self.db.execute("""
                UPDATE settings_declarations SET absent_since = %s
                 WHERE absent_since IS NULL AND name <> ALL(%s::text[])
            """, (now, [declaration[0] for declaration in declarations]), commit=False)

            self.set("4cat.declarations_last_clean_scan", now)

        self.db.commit()

        return len(declarations)

    def get_declarations(self):
        """
        What was last recorded declaring each setting

        Cheap enough to call while rendering a page, unlike `audit_settings()`,
        which also works out how long things have been missing and which
        extensions are on disk.

        :return dict:  Declaration rows, by setting name
        """
        self.with_db()

        return {row["name"]: row for row in self.db.fetchall("SELECT * FROM settings_declarations")}

    def audit_settings(self):
        """
        Find settings in the database that nothing currently declares

        Every setting is put in one of five states. Only `vanished` is ever a
        candidate for removal, and even that is offered to a person rather than
        acted on:

        - `dormant`: declared by an extension that is installed. It may be
          switched off, in which case its settings are not declared this boot,
          but they must survive so that switching it back on restores it.
        - `absent_extension`: declared by an extension that is not installed.
          Re-installing it must restore the previous configuration, so these are
          kept indefinitely.
        - `vanished`: last declared by core, and found missing longer ago than
          the grace period.
        - `recently_absent`: last declared by core and not seen now, but not for
          long enough to be sure. Also everything, whatever its age, when the
          most recent boot was incomplete.
        - `unknown`: nothing ever recorded declaring it. Pre-dates this record
          keeping, or was written directly. Never a candidate, because there is
          no evidence either way.

        Age is measured from `absent_since`, the first complete start-up that
        found a setting gone, and not from `last_seen`, which is only the last
        time 4CAT looked and found it - the gap between two start-ups is the
        operator's uptime, not time spent absent. `absent_since` is written only
        on a complete start-up, so a broken import still cannot age anything
        out, and `scan_is_current` holds everything back besides.

        :return dict:  `scan_is_current` (was the most recent boot complete),
        `last_clean_scan`, and `findings`, a list of undeclared settings
        """
        self.with_db()
        now = int(time.time())

        last_clean_scan = self.get("4cat.declarations_last_clean_scan") or 0

        # a start-up that could not load every module cannot be trusted to say
        # what is missing, so nothing is judged until one that could. Only ever
        # true after a complete boot, which is also what writes last_clean_scan.
        scan_is_current = bool(self.get("4cat.declarations_last_scan_complete"))

        # imported here rather than at the top of the module: helpers builds a
        # CoreConfigManager when it loads, so importing it there is circular
        # only the names are needed, and collecting the metadata forks git once
        # per extension - far too slow for something a page render calls
        from common.lib.helpers import find_extensions
        installed, _ = find_extensions(with_metadata=False)

        rows = self.db.fetchall("""
            SELECT s.name, s.tag, s.value, d.declared_by, d.owner_kind, d.extension_id, d.last_seen, d.absent_since
              FROM settings s
              LEFT JOIN settings_declarations d ON s.name = d.name
             ORDER BY s.name, s.tag
        """)

        occurrences = {}
        for row in rows:
            occurrences.setdefault(row["name"], []).append(row)

        findings = []
        for name, stored in occurrences.items():
            if name in self.config_definition:
                # declared right now, nothing to say about it
                continue

            record = stored[0]
            if not record["declared_by"]:
                state = "unknown"
            elif record["owner_kind"] == "extension":
                state = "dormant" if record["extension_id"] in installed else "absent_extension"
            elif not scan_is_current or not record["absent_since"]:
                # no absence recorded: the last complete start-up still had this
                # setting, so this process not knowing it is not evidence of
                # anything
                state = "recently_absent"
            elif (now - record["absent_since"]) > self.ORPHAN_GRACE_PERIOD:
                state = "vanished"
            else:
                state = "recently_absent"

            findings.append({
                "name": name,
                "state": state,
                "declared_by": record["declared_by"],
                "extension_id": record["extension_id"],
                "last_seen": record["last_seen"],
                "absent_since": record["absent_since"],
                # nothing declares this, so there is no definition to render it
                # with and no field for it on the settings page. Carried so the
                # unused settings page can at least show what is stored.
                "value": record["value"],
                "tags": [row["tag"] for row in stored],
                # ensure_database() only ever writes the global tag, so a value
                # stored against a tag was put there by a person. There is no
                # equivalent signal for the global value: every declared setting
                # gets a row whether or not anyone ever set it.
                "has_tag_override": any(row["tag"] for row in stored)
            })

        return {
            "scan_is_current": scan_is_current,
            "last_clean_scan": last_clean_scan,
            "findings": findings
        }

    def archive_setting(self, name, archived_by=None):
        """
        Move a setting out of use, reversibly

        Every value for the setting - the global one and any stored against a
        tag - moves to `settings_archive`, so nothing is destroyed and
        `restore_setting()` can put it back.

        Only a setting the audit calls `vanished` may be archived, and that is
        checked here rather than trusted from the caller. Anything else is
        either still in use, belongs to an extension that may come back, or has
        no recorded history to judge it by.

        :param str name:  Setting to archive
        :param str archived_by:  Username, recorded so it is clear who did it
        :return int:  Number of stored values moved
        :raises ValueError:  If this setting is not one that may be archived
        """
        self.with_db()

        finding = next((item for item in self.audit_settings()["findings"] if item["name"] == name), None)
        if not finding:
            raise ValueError(f"Setting '{name}' is in use, so cannot be archived.")

        if finding["state"] != "vanished":
            # This is for safety. We may want to allow archiving of other states in future, but for now it is
            # only allowed for vanished settings.
            raise ValueError(f"Setting '{name}' cannot be archived: {self.ARCHIVE_REFUSALS[finding['state']]}")

        # one statement, so the move cannot be left half-done. The front-end
        # shares a single database connection across all of its threads, and any
        # other request served in between can commit it, roll it back, or
        # reconnect out from under it - which for a separate delete and insert
        # means losing the archived copy and keeping the delete.
        # ON CONFLICT because a setting can be archived, come back because
        # something declares it again, and be archived a second time; the newer
        # copy replaces the older one rather than sitting alongside it.
        moved = self.db.fetchall("""
            WITH moved AS (
                DELETE FROM settings WHERE name = %s RETURNING name, value, tag
            )
            INSERT INTO settings_archive (name, value, tag, declared_by, archived_at, archived_by)
            SELECT name, value, tag, %s, %s, %s FROM moved
            ON CONFLICT (name, tag) DO UPDATE SET
                value = EXCLUDED.value,
                declared_by = EXCLUDED.declared_by,
                archived_at = EXCLUDED.archived_at,
                archived_by = EXCLUDED.archived_by
            RETURNING name, tag
        """, (name, finding["declared_by"], int(time.time()), archived_by))

        self.uncache_setting(name, [row["tag"] for row in moved])

        return len(moved)

    def restore_setting(self, name, tag=None):
        """
        Put an archived setting back

        Refused if the setting has a stored value again that someone chose,
        because restoring writes over it and - unlike archiving, which moves
        rather than deletes - there would be nothing left to undo that with. A
        value still at its default is written over: that row is one
        `ensure_database()` created, and refusing on it would leave the archived
        value unreachable for good.

        :param str name:  Setting to restore
        :param str tag:  Restore only the value archived against this tag; the
        empty string is the global value. `None` restores every archived value
        for the setting, which is what `archive_setting()` put there.
        :return int:  Number of stored values restored
        :raises ValueError:  If nothing was archived under this name, or the
        setting is in use again
        """
        self.with_db()

        # fixed SQL either way, only the values are ever interpolated
        conditions = "name = %s" if tag is None else "name = %s AND tag = %s"
        replacements = (name,) if tag is None else (name, tag)

        if not self.db.fetchone(f"SELECT 1 AS found FROM settings_archive WHERE {conditions}", replacements):
            raise ValueError(f"Setting '{name}' is not archived, so cannot be restored.")

        # scoped the same way, so restoring one tag is not refused because a
        # different tag happens to be in use
        # ensure_database() gives every declared setting a row at its default, so
        # a setting declared again after being archived always has one. Refusing
        # on that would strand the archived value for good: it cannot be archived
        # a second time either, because archive_setting() only accepts settings
        # nothing declares. A value still at the default was set by nobody, and
        # the setting is editable in the settings panel again, so writing over it
        # is both safe and undoable by hand.
        #
        # IS DISTINCT FROM rather than <>, so a setting with no default of its own
        # (NULL here) counts every stored value as one somebody chose
        default = json.dumps(self.config_definition[name]["default"]) \
            if name in self.config_definition and "default" in self.config_definition[name] else None

        stored = self.db.fetchone(f"""
            SELECT COUNT(*) AS values_stored,
                   COUNT(*) FILTER (WHERE value IS DISTINCT FROM %s) AS values_configured
              FROM settings WHERE {conditions}
        """, (default, *replacements))

        if stored["values_configured"]:
            raise ValueError(f"Setting '{name}' has a value stored again that is not its default, so restoring "
                             f"would write over it. Archive or change that value first if you want the archived "
                             f"one back.")

        overwritable = bool(stored["values_stored"])

        # as in archive_setting(), one statement so it cannot be left half-done.
        # a plain INSERT rather than an upsert: the check above established that
        # nothing is stored, so if something wrote the setting in between, the
        # unique constraint fails the whole statement and the archived copy
        # stays put - which is the safe way to lose that race. The one exception
        # is a row still at its default, which is written over deliberately; the
        # clause is fixed SQL either way, chosen by the check above.
        on_conflict = "ON CONFLICT (name, tag) DO UPDATE SET value = EXCLUDED.value" if overwritable else ""

        restored = self.db.fetchall(f"""
            WITH moved AS (
                DELETE FROM settings_archive WHERE {conditions} RETURNING name, value, tag
            )
            INSERT INTO settings (name, value, tag)
            SELECT name, value, tag FROM moved
            {on_conflict}
            RETURNING name, tag
        """, replacements)

        self.uncache_setting(name, [row["tag"] for row in restored])

        return len(restored)

    def get_archived_settings(self):
        """
        Settings that have been archived, and can be put back

        :return list:  Archived settings, most recently archived first
        """
        self.with_db()

        return self.db.fetchall("SELECT * FROM settings_archive ORDER BY archived_at DESC, name ASC, tag ASC")

    def get_all_setting_names(self, with_core=True):
        """
        Get names of all settings

        For when the value doesn't matter!

        :param bool with_core:  Also include core (i.e. config.ini) settings
        :return list:  List of setting names known by the database and core settings
        """
        # attempt to initialise the database connection so we can include
        # user settings
        if not self.db:
            self.with_db()

        settings = list(self.core_settings.keys()) if with_core else []
        settings.extend([s["name"] for s in self.db.fetchall("SELECT DISTINCT name FROM settings")])

        return settings

    def get_all(self, is_json=False, user=None, tags=None, with_core=True, memcache=None):
        """
        Get all known settings

        This is *not optimised* but used rarely enough that that doesn't
        matter so much.

        :param bool is_json:  if True, the value is returned as stored and not
        interpreted as JSON if it comes from the database
        :param user:  User object or name. Adds a tag `user:[username]` in
        front of the tag list.
        :param tags:  Tag or tags for the required setting. If a tag is
        provided, the method checks if a special value for the setting exists
        with the given tag, and returns that if one exists. First matching tag
        wins.
        :param bool with_core:  Also include core (i.e. config.ini) settings
        :param MemcacheClient memcache:  Memcache client. If `None`, a thread-local client will be used.

        :return dict: Setting value, as a dictionary with setting names as keys
        and setting values as values.
        """
        for setting in self.get_all_setting_names(with_core=with_core):
            yield setting, self.get(setting, None, is_json, user, tags, memcache)


    def get(self, attribute_name, default=None, is_json=False, user=None, tags=None, memcache=None):
        """
        Get a setting's value from the database

        If the setting does not exist, the provided fallback value is returned.

        :param str attribute_name:  Setting to return.
        :param default:  Value to return if setting does not exist
        :param bool is_json:  if True, the value is returned as stored and not
        interpreted as JSON if it comes from the database
        :param user:  User object or name. Adds a tag `user:[username]` in
        front of the tag list.
        :param tags:  Tag or tags for the required setting. If a tag is
        provided, the method checks if a special value for the setting exists
        with the given tag, and returns that if one exists. First matching tag
        wins.
    :param MemcacheClient memcache:  Memcache client. If `None`, a thread-local client will be used.

        :return:  Setting value, or the provided fallback, or `None`.
        """
        # core settings are not from the database
        # they are therefore also not memcached - too little gain
        if type(attribute_name) is not str:
            raise TypeError(f"attribute_name must be a str, {attribute_name.__class__.__name__} given")

        if attribute_name in self.core_settings:
            # we never get to the database or memcache part of this method if
            # this is a core setting we already know
            return self.core_settings[attribute_name]

        # if trying to access a setting that's not a core setting, attempt to
        # initialise the database connection
        if not self.db:
            self.with_db()

        # get tags to look for
        # copy() because else we keep adding onto the same list, which
        # interacts badly with get_all()
        if tags:
            tags = tags.copy()
        tags = self.get_active_tags(user, tags, memcache)

        # global settings are only ever stored with the global (empty) tag via
        # set(), so there can be no valid tag-specific overrides for them.
        # Always read from the global tag only to avoid returning stale or
        # incorrect tag-specific data that may exist from older versions.
        if attribute_name in self.config_definition and self.config_definition.get(attribute_name, {}).get("global"):
            tags = []

        # now we have all tags - get the config values for each (if available)
        # and then return the first matching one. Add the 'empty' tag at the
        # end to fall back to the global value if no specific one exists.
        tags.append("")

        # Obtain thread-local memcache client if not explicitly given.
        if not memcache:
            memcache = self.get_memcache()

        # first check if we have all the values in memcache, in which case we
        # do not need a database query
        if memcache:
            if threading.get_ident() != memcache.init_thread_id:
                raise RuntimeError("Thread-unsafe use of memcache! Please make sure you are using a configuration "
                                   "wrapper to read with a thread-local memcache connection.")

            cached_values = {tag: memcache.get(self._get_memcache_id(attribute_name, tag), default=CacheMiss) for tag in tags}

        else:
            cached_values = {t: CacheMiss for t in tags}

        # for the tags we could not get from memcache, run a database query
        # (and save to cache if possible)
        missing_tags = [t for t in cached_values if cached_values[t] is CacheMiss]
        if missing_tags:
            # query database for any values within the required tags
            query = "SELECT * FROM settings WHERE name = %s AND tag IN %s"
            replacements = (attribute_name, tuple(missing_tags))
            queried_settings = {setting["tag"]: setting["value"] for setting in self.db.fetchall(query, replacements)}

            if memcache:
                for tag, value in queried_settings.items():
                    memcache.set(self._get_memcache_id(attribute_name, tag), value)

            cached_values.update(queried_settings)

        # there may be some tags for which we still do not have a value at
        # this point. these simply do not have a tag-specific value but that in
        # itself is worth caching, otherwise we're going to query for a
        # non-existent value each time.
        # so: cache a magic value for such setting/tag combinations, and
        # replace the magic value with a CacheMiss in the dict that will be
        # parsed
        unconfigured_magic = "__unconfigured__"
        if memcache:
            for tag in [t for t in cached_values if cached_values[t] is CacheMiss]:
                # should this be more magic?
                memcache.set(self._get_memcache_id(attribute_name, tag), unconfigured_magic)

            for tag in [t for t in cached_values if cached_values[t] == unconfigured_magic]:
                cached_values[tag] = CacheMiss

        # now we may still have some CacheMisses in the values dict, if there
        # was no setting in the database with that tag. So, find the first
        # value that is not a CacheMiss. If nothing matches, try the global tag
        # and if even that does not match (no setting saved at all) return the
        # default
        for tag in tags:
            if tag in cached_values and cached_values.get(tag) is not CacheMiss:
                value = cached_values[tag]
                break
        else:
            value = None

        # parse some values...
        if not is_json and value is not None:
            value = json.loads(value)
        # TODO: Which default should have priority? The provided default feels like it should be the highest priority, but I think that is an old implementation and perhaps should be removed. - Dale
        elif value is None and attribute_name in self.config_definition and "default" in self.config_definition[attribute_name]:
            value = self.config_definition[attribute_name]["default"]
        elif value is None and default is not None:
            value = default

        return value

    def get_active_tags(self, user=None, tags=None, memcache=None):
        """
        Get active tags for given user/tag list

        Used internally to harmonize tag setting for various methods, but can
        also be called directly to verify tag activation.

        :param user:  User object or name. Adds a tag `user:[username]` in
        front of the tag list.
        :param tags:  Tag or tags for the required setting. If a tag is
        provided, the method checks if a special value for the setting exists
        with the given tag, and returns that if one exists. First matching tag
        wins.
    :param MemcacheClient memcache:  Memcache client. If `None`, a thread-local client will be used.
        :return list:  List of tags
        """
        # be flexible about the input types here
        if tags is None:
            tags = []
        elif type(tags) is str:
            tags = [tags]

        user = self._normalise_user(user)

        # user-specific settings are just a special type of tag (which takes
        # precedence), same goes for user groups. so if a user was passed, get
        # that user's tags (including the 'special' user: tag) and add them
        # to the list
        if user:
            user_tags = CacheMiss
            
            if not memcache:
                memcache = self.get_memcache()
                
            if memcache:
                memcache_id = f"_usertags-{user}"
                user_tags = memcache.get(memcache_id, default=CacheMiss)

            if user_tags is CacheMiss:
                user_tags = self.db.fetchone("SELECT tags FROM users WHERE name = %s", (user,))
                if user_tags and memcache:
                    memcache.set(memcache_id, user_tags)

            if user_tags:
                try:
                    tags.extend(user_tags["tags"])
                except (TypeError, ValueError):
                    # should be a JSON list, but isn't
                    pass

            tags.insert(0, f"user:{user}")

        return tags

    def set(self, attribute_name, value, is_json=False, tag="", overwrite_existing=True, memcache=None):
        """
        Insert OR set value for a setting

        If overwrite_existing=True and the setting exists, the setting is updated; if overwrite_existing=False and the
        setting exists the setting is not updated.

        :param str attribute_name:  Attribute to set
        :param value:  Value to set (will be serialised as JSON)
        :param bool is_json:  True for a value that is already a serialised JSON string; False if value is object that needs to
                          be serialised into a JSON string
        :param bool overwrite_existing: True will overwrite existing setting, False will do nothing if setting exists
        :param str tag:  Tag to write setting for
    :param MemcacheClient memcache:  Memcache client. If `None`, a thread-local client will be used.

        :return int: number of updated rows
        """
        # Check value is valid JSON
        if is_json:
            try:
                json.dumps(json.loads(value))
            except json.JSONDecodeError:
                return None
        else:
            try:
                value = json.dumps(value)
            except json.JSONDecodeError:
                return None

        if attribute_name in self.config_definition and self.config_definition.get(attribute_name).get("global"):
            tag = ""

        if overwrite_existing:
            query = "INSERT INTO settings (name, value, tag) VALUES (%s, %s, %s) ON CONFLICT (name, tag) DO UPDATE SET value = EXCLUDED.value"
        else:
            query = "INSERT INTO settings (name, value, tag) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING"

        self.db.execute(query, (attribute_name, value, tag))
        updated_rows = self.db.cursor.rowcount
        self.db.log.debug(f"Updated setting for {attribute_name}: {value} (tag: {tag})")

        if not memcache:
            memcache = self.get_memcache()

        if memcache:
            # invalidate any cached value for this setting
            memcache_id = self._get_memcache_id(attribute_name, tag)
            memcache.delete(memcache_id)

        return updated_rows

    def delete_for_tag(self, attribute_name, tag):
        """
        Delete config override for a given tag

        :param str attribute_name:
        :param str tag:
        :return int: number of deleted rows
        """
        self.db.delete("settings", where={"name": attribute_name, "tag": tag})
        updated_rows = self.db.cursor.rowcount
        client = self.get_memcache()
        if client:
            client.delete(self._get_memcache_id(attribute_name, tag))
        return updated_rows

    def uncache_setting(self, name, tags):
        """
        Drop the cached values for one setting

        Targeted, unlike `clear_cache()`: that flushes the whole memcached
        instance, which 4CAT shares with the rate limiter and with both
        containers' config caches, and is far too blunt for a single setting
        changing.

        Only the given tags are cleared. `get()` also caches a marker for tags
        that have no value at all, but a setting being archived or restored is
        by definition one that nothing declares, so nothing is reading it under
        a tag it never had a value for.

        :param str name:  Setting to forget
        :param tags:  Tags whose cached value should be dropped
        """
        client = self.get_memcache()
        if not client:
            return

        for tag in set(tags):
            client.delete(self._get_memcache_id(name, tag))

    def clear_cache(self):
        """
        Clear cached configuration values

        Flushes the entire memcached instance, so this is for starting with a
        blank slate - the back-end restarting - and not for a single setting
        changing. Use `uncache_setting()` for that.
        """
        client = self.get_memcache()
        if not client:
            return
        client.flush_all()

    def uncache_user_tags(self, users):
        """
        Clear cached user tags

        User tags are cached with memcache if possible to avoid unnecessary
        database roundtrips. This method clears the cached user tags, in case
        a tag is added/deleted from a user.

        :param list users:  List of users, as usernames or User objects
        """
        client = self.get_memcache()
        if client:
            for user in users:
                user = self._normalise_user(user)
                client.delete(f"_usertags-{user}")

    def _normalise_user(self, user):
        """
        Normalise user object

        Users may be passed as a username, a user object, or a proxy of such an
        object. This method normalises this to a string (the username), or
        `None` if no user is provided.

        :param user:  User value to normalise
        :return str|None:  Normalised value
        """

        # can provide either a string or user object
        if type(user) is not str:
            if type(user).__name__ == "LocalProxy":
                # passed on from Flask
                user = user._get_current_object()

            if hasattr(user, "get_id"):
                user = user.get_id()
            elif user != None:  # noqa: E711
                # werkzeug.local.LocalProxy (e.g., user not yet logged in) wraps None; use '!=' instead of 'is not'
                raise TypeError(
                    f"_normalise_user() expects None, a User object or a string for argument 'user', {type(user).__name__} given"
                )

        return user

    def _get_memcache_id(self, attribute_name, tags=None):
        """
        Generate a memcache key for a config setting request

        This includes the relevant user name/tags because the value may be
        different depending on the value of these parameters.

        :param str attribute_name:
        :param str|list tags:
        :return str:
        """
        if tags and isinstance(tags, str):
            tags = [tags]

        tag_bit = []
        if tags:
            tag_bit.append("|".join(tags))

        memcache_id = attribute_name
        if tag_bit:
            memcache_id += f"-{'-'.join(tag_bit)}"

        return memcache_id.encode("ascii")

    def __getattr__(self, attr):
        """
        Getter so we can directly request values

        :param attr:  Config setting to get
        :return:  Value
        """

        if attr in dir(self):
            # an explicitly defined attribute should always be called in favour
            # of this passthrough
            attribute = getattr(self, attr)
            return attribute
        else:
            return self.get(attr)


class ConfigWrapper(BaseConfigReader):
    """
    Wrapper for the config manager

    Allows setting a default set of tags or user, so that all subsequent calls
    to `get()` are done for those tags or that user. Can also adjust tags based
    on the HTTP request, if used in a Flask context.
    """
    def __init__(self, config, user=None, tags=None, request=None):
        """
        Initialise config wrapper

        :param ConfigManager config:  Initialised config manager
        :param user:  User to get settings for
        :param tags:  Tags to get settings for
        :param request:  Request to get headers from. This can be used to set
        a particular tag based on the HTTP headers of the request, e.g. to
        serve 4CAT with a different configuration based on the proxy server
        used.
        """
        if type(config) is ConfigWrapper:
            # let's not do nested wrappers, but copy properties unless
            # provided explicitly
            self.user = user if user else config.user
            self.tags = tags if tags else config.tags
            self.request = request if request else config.request
            self.config = config.config
            # legacy: previous versions cached a per-request memcache client; now resolved inside ConfigManager
        else:
            self.config = config
            self.user = user
            self.tags = tags
            self.request = request

        # this ensures the user object in turn reads from the wrapper
        if self.user:
            self.user.with_config(self, rewrap=False)


    def set(self, *args, **kwargs):
        """
        Wrap `set()`

        :param args:
        :param kwargs:
        :return:
        """
        if "tag" not in kwargs and self.tags:
            kwargs["tag"] = self.tags

        # ConfigManager resolves thread-local memcache internally

        return self.config.set(*args, **kwargs)

    def get_all(self, *args, **kwargs):
        """
        Wrap `get_all()`

        Takes the `user`, `tags` and `request` given when initialised into
        account. If `tags` is set explicitly, the HTTP header-based override
        is not applied.

        :param args:
        :param kwargs:
        :return:
        """
        if "user" not in kwargs and self.user:
            kwargs["user"] = self.user

        if "tags" not in kwargs:
            kwargs["tags"] = self.tags if self.tags else []
            kwargs["tags"] = self.request_override(kwargs["tags"])

        # ConfigManager resolves thread-local memcache internally

        return self.config.get_all(*args, **kwargs)

    def get(self, *args, **kwargs):
        """
        Wrap `get()`

        Takes the `user`, `tags` and `request` given when initialised into
        account. If `tags` is set explicitly, the HTTP header-based override
        is not applied.

        :param args:
        :param kwargs:
        :return:
        """
        if "user" not in kwargs:
            kwargs["user"] = self.user

        if "tags" not in kwargs:
            kwargs["tags"] = self.tags if self.tags else []
            kwargs["tags"] = self.request_override(kwargs["tags"])

        # ConfigManager resolves thread-local memcache internally

        return self.config.get(*args, **kwargs)

    def get_active_tags(self, user=None, tags=None):
        """
        Wrap `get_active_tags()`

        Takes the `user`, `tags` and `request` given when initialised into
        account. If `tags` is set explicitly, the HTTP header-based override
        is not applied.

        :param user:
        :param tags:
        :return list:
        """
        active_tags = self.config.get_active_tags(user, tags)
        if not tags:
            active_tags = self.request_override(active_tags)
        return active_tags

    def request_override(self, tags):
        """
        Force tag via HTTP request headers

        To facilitate loading different configurations based on the HTTP
        request, the request object can be passed to the ConfigWrapper and
        if a certain request header is set, the value of that header will be
        added to the list of tags to consider when retrieving settings.

        See the flask.proxy_secret config setting; this is used to prevent
        users from changing configuration by forging the header.

        :param list|str tags:  List of tags to extend based on request
        :return list:  Amended list of tags
        """
        if type(tags) is str:
            tags = [tags]

        # use self.config.get here, not self.get, because else we get infinite
        # recursion (since self.get can call this method)
        if self.request and self.request.headers.get("X-4Cat-Config-Tag") and \
            self.config.get("flask.proxy_secret") and \
            self.request.headers.get("X-4Cat-Config-Via-Proxy") == self.config.get("flask.proxy_secret"):
            # need to ensure not just anyone can add this header to their
            # request!
            # to this end, the second header must be set to the secret value;
            # if it is not set, assume the headers are not being configured by
            # the proxy server
            if not tags:
                tags = []

            # can never set admin tag via headers (should always be user-based)
            forbidden_overrides = ("admin",)
            tags += [tag for tag in self.request.headers.get("X-4Cat-Config-Tag").split(",") if tag not in forbidden_overrides]

        return tags


    def __getattr__(self, item):
        """
        Generic wrapper

        Just pipe everything through to the config object

        :param item:
        :return:
        """
        if hasattr(self.config, item):
            return getattr(self.config, item)
        elif hasattr(self, item):
            return getattr(self, item)
        else:
            raise AttributeError(f"'{self.__name__}' object has no attribute '{item}'")


class CoreConfigManager(ConfigManager):
    """
    A configuration reader that can only read from core settings

    Can be used in thread-unsafe context and when no database is present.
    """
    def with_db(self, db=None):
        """
        Raise a RuntimeError when trying to link a database connection

        :param db:
        """
        raise RuntimeError("Trying to read non-core configuration value from a CoreConfigManager")