import logging.handlers
import subprocess
from collections import namedtuple
import sys
import os

from functools import partial
from pathlib import Path

# first-run.py ensures everything is set up right when running 4CAT for the first time
first_run = Path(__file__).parent.parent.joinpath("helper-scripts", "first-run.py")
result = subprocess.run([sys.executable, str(first_run)], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)

if result.returncode != 0:
    print("Unexpected error while preparing 4CAT. You may need to re-install 4CAT.")
    print("stdout:\n".join(["  " + line for line in result.stdout.decode("utf-8").split("\n")]))
    print("stderr:\n".join(["  " + line for line in result.stderr.decode("utf-8").split("\n")]))
    exit(1)

# the following are imported *after* the first-run stuff because they may rely
# on things set up in there - or should not run unless first-run completes
# successfully!
from flask import Flask, g, request, current_app  # noqa: E402
from flask_login import LoginManager, current_user  # noqa: E402
from flask_limiter import Limiter  # noqa: E402
from flask_limiter.util import get_remote_address  # noqa: E402
from werkzeug.middleware.proxy_fix import ProxyFix  # noqa: E402

from common.config_manager import ConfigManager, ConfigWrapper  # noqa: E402
from common.lib.database import Database  # noqa: E402
from common.lib.logger import Logger  # noqa: E402
from common.lib.queue import JobQueue  # noqa: E402
from common.lib.module_loader import ModuleCollector  # noqa: E402

from common.lib.user import User  # noqa: E402
from webtool.lib.helpers import generate_css_colours  # noqa: E402
from webtool.lib.openapi_collector import OpenAPICollector  # noqa: E402

# make a web app!
app = Flask(__name__)
config = ConfigManager()

# this ensures that HTTPS is properly applied to built URLs even if the app
# is running behind a proxy
# see https://stackoverflow.com/a/45333882
proxy_overrides = {param: 1 for param in config.get("flask.proxy_override")}
app.wsgi_app = ProxyFix(app.wsgi_app, **proxy_overrides)

# set up logger for error logging etc
log_folder = config.get('PATH_ROOT').joinpath(config.get('PATH_LOGS'))
if config.get("USING_DOCKER"):
    # in Docker it is useful to have two separate files - since 4CAT is also
    # in two separate containers
    log = Logger(logger_name='4cat-frontend', log_path=log_folder.joinpath("frontend_4cat.log"))
else:
    log = Logger(logger_name='4cat-frontend', log_path=log_folder.joinpath("4cat.log"))

log.load_webhook(config)

# test memcache
# this is also done in the backend, but the frontend may not be able to connect
# while the backend is, for example
if config.get("MEMCACHE_SERVER"):
    if config.memcache:
        log.debug("Memcache connection initialized")
    else:
        log.warning(
            f"Memcache server address configured, but connection could not be initialized at "
            f"{config.get('MEMCACHE_SERVER')}. Front-end configuration cache inactive."
        )

# set up logging for Gunicorn
# this redirects Gunicorn log messages to the logger instantiated above - more
# sensible than having yet another separate log file
if "gunicorn" in os.environ.get("SERVER_SOFTWARE", ""):
    # Add Gunicorn error log to main app logger
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level) # debug is int 10

    # Gunicorn Error Log file
    error_file_path = config.get('PATH_LOGS').joinpath('error_gunicorn.log')
    file_handler = logging.handlers.RotatingFileHandler(
                                                        filename=error_file_path,
                                                        maxBytes=int( 50 * 1024 * 1024),
                                                        backupCount= 1,
                                                        )
    logFormatter = logging.Formatter("%(asctime)s [%(levelname)-5.5s]  %(message)s")
    file_handler.setFormatter(logFormatter)
    app.logger.addHandler(file_handler)

# helper decorator to facilitate the timing of routes when running in debug
# mode - if not running in debug mode, nothing happens.
if app.logger.getEffectiveLevel() == 10:
    # if we're in debug mode, we want to see how long it takes to load datasets
    import time
    from functools import wraps
    def time_this(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            r = func(*args, **kwargs)
            app.logger.debug("%s dataset took %.2f seconds" % (func.__name__, time.time() - start_time))
            return r
        return wrapper
else:
    def time_this(func):
        return func
app.time_this = time_this

# 4CAT compontents we need access to from within the web app
db = Database(logger=log, dbname=config.get("DB_NAME"), user=config.get("DB_USER"),
              password=config.get("DB_PASSWORD"), host=config.get("DB_HOST"),
              port=config.get("DB_PORT"), appname="frontend")
config.with_db(db)
queue = JobQueue(logger=log, database=db)

# make sure a secret key was set in the config file, for secure session cookies
if not config.get("flask.secret_key") or config.get("flask.secret_key") == "REPLACE_THIS":
    raise Exception("You need to set the flask.secret_key setting running the web tool.")

# initialize Flask configuration from config manager
app.config.from_mapping({
    "FLASK_APP": config.get("flask.flask_app"),
    "SECRET_KEY": config.get("flask.secret_key"),
    "SERVER_NAME": config.get("flask.server_name"),
    "SERVER_HTTPS": config.get("flask.https"),
    "HOSTNAME_WHITELIST": config.get("flask.autologin.hostnames"),
    "HOSTNAME_WHITELIST_NAME": config.get("flask.autologin.name"),
    "HOSTNAME_WHITELIST_API": config.get("flask.autologin.api"),
    "PREFERRED_URL_SCHEME": "https" if config.get("flask.https") else "http"
})

# Set number of form parts to accept (default is 1000; affects number of files that can be uploaded)
app.request_class.max_form_parts = config.get("flask.max_form_parts", 1000)

# set up login manager
app.login_manager = LoginManager()
app.login_manager.anonymous_user = partial(User.get_by_name, db=db, name="anonymous")
app.login_manager.init_app(app)
app.login_manager.login_view = "user.show_login"

# initialize rate limiter - memcache can serve as the storage backend, if not
# available, direct memory storage will be used
if config.memcache:
    app.limiter = Limiter(app=app, key_func=get_remote_address, storage_uri=f"memcached://{config.get('MEMCACHE_SERVER')}")
else:
    app.limiter = Limiter(app=app, key_func=get_remote_address)

# read these once, because we need them for each request but they will never
# change without a restart
app.autologin = namedtuple("AutologinSettings", ("hostnames", "api"))
app.autologin.hostnames = config.get("flask.autologin.hostnames")
app.autologin.api = config.get("flask.autologin.api")

# now create an app context to import Blueprints into
# the app context allows us to pass some values for use inside the Blueprints
# which they can access via `current_app` - this eliminates the need for
# circular imports (importing app from inside the Blueprint)
with app.app_context():
    # these are needed in contexts where we cannot read from `g` (because that
    # gets populated before `before_request`), but can read from current_app
    # instead. Note that where possible g.config should always be preferred
    # over app.fourcat_config because the former is not user-aware!
    app.openapi = OpenAPICollector(app)
    app.log = log
    app.db = db
    app.fourcat_config = config
    app._memcache_initialized = False  # flag to check if memcache was initialized
    app.fourcat_modules = ModuleCollector(app.fourcat_config)

    # import all views; these can only be imported here because they rely on
    # current_app for initialisation
    import webtool.views.views_restart  # noqa: E402
    import webtool.views.views_admin  # noqa: E402
    import webtool.views.views_extensions  # noqa: E402
    import webtool.views.views_user  # noqa: E402
    import webtool.views.views_dataset  # noqa: E402
    import webtool.views.views_misc  # noqa: E402
    import webtool.views.views_explorer  # noqa: E402
    import webtool.views.api_standalone  # noqa: E402
    import webtool.views.api_tool  # noqa: E402
    
    app.register_blueprint(webtool.views.views_restart.component)
    app.register_blueprint(webtool.views.views_admin.component)
    app.register_blueprint(webtool.views.views_extensions.component)
    app.register_blueprint(webtool.views.views_user.component)
    app.register_blueprint(webtool.views.views_dataset.component)
    app.register_blueprint(webtool.views.views_misc.component)
    app.register_blueprint(webtool.views.views_explorer.component)
    app.register_blueprint(webtool.views.api_standalone.component)
    app.register_blueprint(webtool.views.api_tool.component)

    @app.before_request
    def before_request():
        """
        Register context-aware 4CAT objects per request

        Particularly the config reader should be wrapped to account for the
        request's active user, so these are registered in the global `g`
        contextual namespace.
        """
        if request.path.startswith("/static/") or request.path.endswith("favicon.ico"):
            # in contexts where we're serving static files through slack, save
            # some overhead
            return
        
         # Initialize memcache once per worker
        if not app._memcache_initialized:
            app.fourcat_config.memcache = app.fourcat_config.load_memcache()
            app._memcache_initialized = True

        g.queue = queue
        g.db = db
        g.log = log
        g.config = ConfigWrapper(app.fourcat_config, user=current_user, request=request)
        g.modules = current_app.fourcat_modules

        current_user.with_config(g.config)

    # import custom jinja2 template filters

    # these also benefit from current_app
    import webtool.lib.template_filters  # noqa: E402

    # ensure that colour definition CSS file is present - the CSS colours can be
    # changed by the admin so we need to regenerate the CSS file to make sure it
    # is up to date. Might want to use e.g. SCSS in the future...
    generate_css_colours(config)

# run it (when called directly)
if __name__ == "__main__":
    print('Starting server...')
    app.run(host='0.0.0.0', debug=True)
