"""
Routes for restarting 4CAT

This is a relatively complex set of routes so they get their own file!
"""
import packaging.version
import subprocess
import threading
import requests
import datetime
import signal
import shutil
import shlex
import time
import json
import sys
import os

from pathlib import Path
from flask import render_template, request, flash, get_flashed_messages, jsonify

from flask_login import login_required, current_user

from webtool import app, queue, config
from webtool.lib.helpers import setting_required, check_restart_request

from common.lib.helpers import get_github_version

from common.config_manager import ConfigWrapper
config = ConfigWrapper(config, user=current_user, request=request)

@app.route("/admin/trigger-restart/", methods=["POST", "GET"])
@login_required
@setting_required("privileges.admin.can_restart")
def trigger_restart():
    """
    Trigger a 4CAT upgrade or restart

    Calls the migrate.py script with parameters to make it check out the latest
    4CAT release available from the configured repository, and restart the
    daemon and front-end.

    One issue is that restarting the front-end is not always possible, because
    it depends on how the server is set up. In practice, the 4cat.wsgi file is
    touched, so if the server is set up to reload when that file updates (as is
    common in e.g. mod_wsgi) it should trigger a reload.
    """
    # figure out the versions we are dealing with
    current_version_file = Path(config.get("PATH_ROOT"), "config/.current-version")
    if current_version_file.exists():
        current_version = current_version_file.open().readline().strip()
    else:
        current_version = "unknown"

    code_version = Path(config.get("PATH_ROOT"), "VERSION").open().readline().strip()
    try:
        github_version = get_github_version(timeout=5)
        release_notes = github_version[1]
        github_version = github_version[0]
    except (json.JSONDecodeError, requests.RequestException):
        github_version = "unknown"
        release_notes = None

    # upgrade is available if we have all info and the release is newer than
    # the currently checked out code
    can_upgrade = not (github_version == "unknown" or code_version == "unknown" or packaging.version.parse(
        current_version) >= packaging.version.parse(github_version))

    lock_file = Path(config.get("PATH_ROOT"), "config/restart.lock")
    if request.method == "POST" and lock_file.exists():
        flash("A restart is already in progress. Wait for it to complete. Check the process log for more details.")

    elif request.method == "POST":
        # run upgrade or restart via shell commands
        mode = request.form.get("action")
        allowed_modes = ["upgrade", "restart"]
        if config.get("privileges.can_upgrade_to_dev"):
            allowed_modes.append("upgrade-to-branch")

        if mode not in allowed_modes:
            return "Invalid mode", 400

        # ensure lockfile exists - will be written to later by worker
        lock_file.touch()

        # this log file is used to keep track of the progress, and will also
        # be viewable in the web interface
        restart_log_file = Path(config.get("PATH_ROOT"), config.get("PATH_LOGS"), "restart.log")
        with restart_log_file.open("w") as outfile:
            outfile.write(
                f"{mode.capitalize().replace('-', ' ')} initiated at server timestamp {datetime.datetime.now().strftime('%c')}\n")
            outfile.write(f"Telling 4CAT to {mode.replace('-', ' ')} via job queue...\n")
        # this file will be updated when the upgrade runs
        # and it is shared between containers, but we will need to upgrade the
        # front-end separately - so keep a local copy for the latter step
        if config.get("USING_DOCKER") and mode.startswith("upgrade"):
            frontend_version_file = current_version_file.with_name(".current-version-frontend")
            shutil.copy(current_version_file, frontend_version_file)

        # from here on, the back-end takes over
        details = {} if not request.form.get("branch") else {"branch": request.form["branch"]}
        queue.add_job("restart-4cat", details, mode)
        flash(f"{mode.capitalize().replace('-', ' ')} initiated. Check process log for progress.")

    return render_template("controlpanel/restart.html", flashes=get_flashed_messages(), in_progress=lock_file.exists(),
                           can_upgrade=can_upgrade, current_version=current_version, tagged_version=github_version,
                           release_notes=release_notes)


@app.route("/admin/trigger-frontend-upgrade/", methods=["POST"])
def upgrade_frontend():
    """
    Run migrate.py in the frontend's environment

    This only really makes sense when running 4CAT with Docker. In that case,
    the frontend runs in its own container, so it needs to run migrate.py for
    that container to load the latest code and update dependencies. To that
    end, the back-end can request this route, which will trigger that
    procedure. The request ends after migrate.py has finished running after
    which it is up to the back-end to determine what to do next.

    This route expects a file config/.current-version-frontend to exist. This
    file should be created before requesting this route so that the front-end
    knows what version it is running, since config/.current-version will have
    been updated by the back-end at this point to reflect the newer version
    after that container's upgrade.
    """
    # this route only makes sense in a Docker context
    if not config.get("USING_DOCKER") or not check_restart_request():
        return app.login_manager.unauthorized()

    restart_log_file = Path(config.get("PATH_ROOT"), config.get("PATH_LOGS"), "restart.log")
    frontend_version_file = Path(config.get("PATH_ROOT"), "config/.current-version-frontend")
    if not frontend_version_file.exists():
        return jsonify({"status": "error", "message": "No version file found"})

    log_stream = restart_log_file.open("a")

    log_stream.write("Updating code for front-end Docker container\n")
    log_stream.flush()
    upgrade_ok = False

    command = sys.executable + " helper-scripts/migrate.py --component frontend --repository %s --yes --current-version %s" % (
        shlex.quote(config.get("4cat.github_url")), shlex.quote(str(frontend_version_file)))

    # there should be one and only one job of this type, with the parameters of
    # our upgrade. it determines if we update to the latest release or to a
    # branch
    upgrade_job = queue.get_job("restart-4cat", restrict_claimable=False)
    command += " --release" if not upgrade_job or not upgrade_job.details.get("branch") else f" --branch {shlex.quote(upgrade_job.details['branch'])}"

    try:
        response = subprocess.run(shlex.split(command), stdout=log_stream, stderr=subprocess.STDOUT, text=True,
                                  check=True, cwd=str(config.get("PATH_ROOT")), stdin=subprocess.DEVNULL)
        if response.returncode != 0:
            raise RuntimeError(f"Unexpected return code {response.returncode}")
        upgrade_ok = True

    except (RuntimeError, subprocess.CalledProcessError) as e:
        # this is bad :(
        message = f"Upgrade unsuccessful ({e}). Check log files for details. You may need to manually restart 4CAT."
        log_stream.write(message + "\n")

    finally:
        log_stream.close()
        frontend_version_file.unlink()

    return jsonify({"status": "OK" if upgrade_ok else "error", "message": ""})


@app.route("/admin/trigger-frontend-restart/", methods=["POST"])
def trigger_restart_frontend():
    """
    Trigger a restart of the 4CAT front-end

    How to do this depends on what server software is used. The two most common
    options are supported (gunicorn and mod_wsgi).

    If restarting is not supported a JSON is returned explaining so. In that
    case the user needs to restart the server in some other way.
    """
    status = "error"

    def server_killer(pid, sig, touch_path=None):
        """
        Helper function. Gives Flask time to complete the request before
        sending the signal.
        """
        def kill_function():
            if touch_path:
                touch_path.touch()

            time.sleep(2)
            os.kill(pid, sig)

        return kill_function

    # ensure a restart is in progress and the request is from the backend
    # alternatively, this can be called directly, but only with the right
    # privileges
    if not check_restart_request() and not config.get("privileges.admin.can_restart"):
        return app.login_manager.unauthorized()

    # we support restarting with gunicorn and apache/mod_wsgi
    # nginx would usually be a front for gunicorn so that use case is also
    # covered
    # flask additionally lists waitress as a standalone wsgi server
    # we currently do not support this (but it may be easy to add)
    message = ""

    # determine if we're in uwsgi
    # if not in uwsgi, importing will always fail!
    in_uwsgi = False
    try:
        import uwsgi
        in_uwsgi = True
    except (ModuleNotFoundError, ImportError):
        pass

    if in_uwsgi:
        message = "Detected Flask running in uWSGI, sending SIGHUP"
        kill_thread = threading.Thread(target=server_killer(uwsgi.masterpid(), signal.SIGHUP))
        kill_thread.start()

    elif "gunicorn" in os.environ.get("SERVER_SOFTWARE", ""):
        # no easy way to get pid (unless we run gunicorn with a pid file, but
        # that is not guaranteed)
        # so traverse up the process tree, from the current process, to the
        # uppermost process running a "gunicorn" command
        import psutil
        process = psutil.Process(os.getpid()).parent()
        gunicorn_pid = None
        while process:
            try:
                if any([c for c in process.cmdline() if c.endswith("gunicorn")]):
                    # technically this matches anything ending in "gunicorn",
                    # also e.g. cmdline params. But should be good enough
                    # (worst case we send a HUP to the wrong process)
                    gunicorn_pid = process.pid
            except psutil.NoSuchProcess:
                break

            process = process.parent()

        if not gunicorn_pid:
            message = ("4CAT is running with Gunicorn, but could not find Gunicorn PID. You will need to restart the "
                       "front-end manually.")

        else:
            message = "Detected Flask running in Gunicorn, sending SIGHUP."
            kill_thread = threading.Thread(target=server_killer(gunicorn_pid, signal.SIGHUP))
            kill_thread.start()
            status = "OK"

    elif os.environ.get("APACHE_PID_FILE", "") != "":
        # apache
        # mod_wsgi? touching the file is always safe
        message = "Detected Flask running in mod_wsgi, touching 4cat.wsgi."
        wsgi_file = Path(config.get("PATH_ROOT"), "webtool", "4cat.wsgi")

        # send a signal to apache to reload if running in daemon mode
        if os.environ.get("mod_wsgi.process_group") not in (None, ""):
            message = "Detected Flask running in mod_wsgi as daemon, sending SIGINT."
            kill_thread = threading.Thread(target=server_killer(os.getpid(), signal.SIGINT, touch_path=wsgi_file))
            kill_thread.start()
            status = "OK"
        else:
            wsgi_file.touch()

    else:
        return jsonify({"status": "error", "message": "4CAT is not hosted with gunicorn, uwsgi or mod_wsgi. Cannot "
                                                      "restart 4CAT's front-end remotely; you have to do so manually."})

    # up to whatever called this to monitor for restarting
    return jsonify({"status": status, "message": message})


@app.route("/admin/restart-log/")
@setting_required("privileges.admin.can_restart")
def restart_log():
    """
    Retrieve the remote restart log file

    Useful to display in the web interface to keep track of how this is going!

    :return:
    """
    log_file = Path(config.get("PATH_ROOT"), config.get("PATH_LOGS"), "restart.log")
    if log_file.exists():
        with log_file.open() as infile:
            return infile.read()
    else:
        return "Not Found", 404
