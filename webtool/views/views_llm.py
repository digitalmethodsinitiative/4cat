"""
4CAT views for LLM server management
"""
import time
import re

from flask import Blueprint, render_template, flash, get_flashed_messages, redirect, url_for, request, g
from flask_login import login_required

from webtool.lib.helpers import setting_required, error
from common.lib.llm.llm_client import LLMServerClient

component = Blueprint("llm", __name__)


@component.route("/admin/llm/", methods=["GET", "POST"])
@login_required
@setting_required("privileges.admin.can_manage_settings")
def llm_panel():
    """
    LLM Server management panel

    Shows server status, available models, and controls to pull/delete/refresh
    models. Pull, delete, and refresh operations are queued as LLMServerManager
    jobs rather than run synchronously.
    """
    if not g.config.get("llm.access"):
        return error(403, message="LLM access is not enabled on this server.")

    servers = g.config.get("llm.servers", {})
    models = g.config.get("llm.available_models", {})

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        server = request.form.get("server", "").strip()
        details = {"server": server} if server else {}

        if action == "refresh":
            # Queue a one-time manual refresh job; use a timestamp-based remote_id
            # so it is always accepted even if a periodic job already exists.
            g.queue.add_job("manage-llm", details={"task": "refresh"},
                            remote_id=f"manage-llm-manual-{int(time.time())}")
            flash("Requesting model list from LLM servers.")

        elif action == "pull":
            model_name = request.form.get("model_name", "").strip()
            if model_name:
                g.queue.add_job("manage-llm", details={**details, "task": "pull"}, remote_id=model_name)
                flash(f"Model '{model_name}' was queued for installation.")
            else:
                flash("Please provide a model name to install.")

        elif action == "delete":
            model = request.form.get("model", "").strip()
            if model and model in models:
                g.queue.add_job("manage-llm", details={**details, "task": "delete"}, remote_id=model)
                flash(f"Model '{model}' was queued for deletion.")

        elif action == "save-enabled":
            enabled_models = []
            for field, value in request.form.items():
                if field.startswith("enable:") and value == "on":
                    model = re.sub(r"^enable:", "", field)
                    if model in models:
                        enabled_models.append(model)

            g.config.set("llm.enabled_models", enabled_models)
            flash(f"Enabled models updated")

        return redirect(url_for("llm.llm_panel"))

    # --- GET: render panel ---

    for server_id, server in servers.items():
        client = LLMServerClient.get_client(g.config, server, g.log)

        if server_status := client.get_status():
            server_status = "online" if server_status == 200 else f"error (HTTP {server_status})"
        else:
            server_status = "unreachable"

        servers[server_id]["status"] = server_status

    available_models = g.config.get("llm.available_models", {}) or {}
    enabled_models = list(g.config.get("llm.enabled_models", []) or [])

    # order is important for grouping per server
    available_models = {k: available_models[k] for k in sorted(available_models, key=lambda k: available_models[k]["server"])}

    llm_jobs = [
        job for job in g.queue.get_all_jobs("manage-llm", restrict_claimable=False) if not job.data["interval"]
    ]

    return render_template(
        "controlpanel/llm-server.html",
        flashes=get_flashed_messages(),
        servers=servers,
        available_models=available_models,
        enabled_models=enabled_models,
        tasks_running=llm_jobs,
    )
