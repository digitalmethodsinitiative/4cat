"""
4CAT views for LLM server management
"""
import time

import requests

from flask import Blueprint, render_template, flash, get_flashed_messages, redirect, url_for, request, g
from flask_login import login_required

from webtool.lib.helpers import setting_required, error
from common.lib.llm.llm_client import LLMProviderClient

component = Blueprint("llm", __name__)


@component.route("/admin/llm/", methods=["GET", "POST"])
@login_required
@setting_required("privileges.admin.can_manage_settings")
def llm_panel():
    """
    LLM Server management panel

    Shows server status, available models, and controls to pull/delete/refresh
    models. Pull, delete, and refresh operations are queued as LLMProviderManager
    jobs rather than run synchronously.
    """
    if not g.config.get("llm.access"):
        return error(403, message="LLM access is not enabled on this server.")

    providers = g.config.get("llm.providers", [])

    if request.method == "POST":
        action = request.form.get("action", "").strip()
        provider = request.form.get("provider", "").strip()
        details = {"provider": provider} if provider else {}

        if action == "refresh":
            # Queue a one-time manual refresh job; use a timestamp-based remote_id
            # so it is always accepted even if a periodic job already exists.
            g.queue.add_job("manage-llm", details={**details, "task": "refresh"},
                            remote_id=f"manage-llm-manual-{int(time.time())}")
            flash("Model refresh job queued.")

        elif action == "pull":
            model_name = request.form.get("model_name", "").strip()
            if model_name:
                g.queue.add_job("manage-llm", details={**details, "task": "pull"}, remote_id=model_name)
                flash(f"Pull job queued for model '{model_name}'.")
            else:
                flash("Please provide a model name to pull.")

        elif action == "delete":
            model_name = request.form.get("model_name", "").strip()
            if model_name:
                g.queue.add_job("manage-llm", details={**details, "task": "delete"}, remote_id=model_name)
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

    for i, provider in enumerate(providers):
        client = LLMProviderClient.get_client(g.config, provider)

        if provider_status := client.get_status():
            server_status = "online" if provider_status == 200 else f"error (HTTP {provider_status})"
        else:
            server_status = "unreachable"

        providers[i]["status"] = server_status

    available_models = g.config.get("llm.available_models", {}) or {}
    enabled_models = list(g.config.get("llm.enabled_models", []) or [])

    return render_template(
        "controlpanel/llm-server.html",
        flashes=get_flashed_messages(),
        providers=providers,
        available_models=available_models,
        enabled_models=enabled_models,
    )
