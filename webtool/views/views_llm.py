"""
4CAT views for LLM server management
"""
import time

import requests

from flask import Blueprint, render_template, flash, get_flashed_messages, redirect, url_for, request, g
from flask_login import login_required

from webtool.lib.helpers import setting_required, error

component = Blueprint("llm", __name__)


@component.route("/admin/llm/", methods=["GET", "POST"])
@login_required
@setting_required("privileges.admin.can_manage_settings")
def llm_panel():
    """
    LLM Server management panel

    Shows server status, available models, and controls to pull/delete/refresh
    models. Pull, delete, and refresh operations are queued as OllamaManager
    jobs rather than run synchronously.
    """
    if not g.config.get("llm.access"):
        return error(403, message="LLM access is not enabled on this server.")

    if request.method == "POST":
        action = request.form.get("action", "").strip()

        if action == "refresh":
            # Queue a one-time manual refresh job; use a timestamp-based remote_id
            # so it is always accepted even if a periodic job already exists.
            g.queue.add_job("manage-ollama", details={"task": "refresh"},
                            remote_id=f"manage-ollama-manual-{int(time.time())}")
            flash("Model refresh job queued.")

        elif action == "pull":
            model_name = request.form.get("model_name", "").strip()
            if model_name:
                g.queue.add_job("manage-ollama", details={"task": "pull"}, remote_id=model_name)
                flash(f"Pull job queued for model '{model_name}'.")
            else:
                flash("Please provide a model name to pull.")

        elif action == "delete":
            model_name = request.form.get("model_name", "").strip()
            if model_name:
                g.queue.add_job("manage-ollama", details={"task": "delete"}, remote_id=model_name)
                flash(f"Delete job queued for model '{model_name}'.")

        elif action == "enable":
            model_name = request.form.get("model_name", "").strip()
            if model_name:
                enabled_models = list(g.config.get("llm.enabled_models", []) or [])
                if model_name not in enabled_models:
                    enabled_models.append(model_name)
                    g.config.set("llm.enabled_models", enabled_models)
                flash(f"Model '{model_name}' enabled.")

        elif action == "disable":
            model_name = request.form.get("model_name", "").strip()
            if model_name:
                enabled_models = list(g.config.get("llm.enabled_models", []) or [])
                if model_name in enabled_models:
                    enabled_models.remove(model_name)
                    g.config.set("llm.enabled_models", enabled_models)
                flash(f"Model '{model_name}' disabled.")

        return redirect(url_for("llm.llm_panel"))

    # --- GET: render panel ---

    llm_server = g.config.get("llm.server", "")
    server_status = "not configured"

    if llm_server:
        headers = {"Content-Type": "application/json"}
        llm_api_key = g.config.get("llm.api_key", "")
        llm_auth_type = g.config.get("llm.auth_type", "")
        if llm_api_key and llm_auth_type:
            headers[llm_auth_type] = llm_api_key

        try:
            resp = requests.get(f"{llm_server}/api/tags", headers=headers, timeout=5)
            server_status = "online" if resp.status_code == 200 else f"error (HTTP {resp.status_code})"
        except requests.Timeout:
            server_status = "unreachable (timeout)"
        except requests.RequestException as e:
            server_status = f"unreachable ({e})"

    available_models = g.config.get("llm.available_models", {}) or {}
    enabled_models = list(g.config.get("llm.enabled_models", []) or [])

    return render_template(
        "controlpanel/llm-server.html",
        flashes=get_flashed_messages(),
        llm_server=llm_server,
        server_status=server_status,
        available_models=available_models,
        enabled_models=enabled_models,
    )
