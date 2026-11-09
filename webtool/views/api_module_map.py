"""
Module map API.

Thin JSON endpoints over `common.lib.module_map` -- each just builds the
ModuleMap and calls one method, so the data layer stays in common/lib and any
UI can be built against these without touching it. 'Module' here covers both
processors and data sources: a data source's search worker is a processor too,
and the map flags it with `is_datasource`.

Login-gated. Demonstrates what the declarative Compatibility specs make computable
(search, "how to run this", shape buckets, follow-ups) with no datasets and no
database.
"""
from flask import Blueprint, current_app, jsonify, request
from flask_login import login_required

from webtool.lib.helpers import error, module_map as _module_map

component = Blueprint("modulemap", __name__)
api_ratelimit = current_app.limiter.shared_limit("3 per second", scope="api")


@component.route("/api/module-map/catalogue")
@api_ratelimit
@login_required
def module_map_catalogue():
    """Every module - processor or data source - with display metadata and flags."""
    return jsonify({"modules": _module_map().catalogue()})


@component.route("/api/module-map/categories")
@api_ratelimit
@login_required
def module_map_categories():
    """{category: [types]} for grouped browsing."""
    return jsonify(_module_map().categories())


@component.route("/api/module-map/search")
@api_ratelimit
@login_required
def module_map_search():
    """Find modules by a substring of type/title/category/description."""
    query = request.args.get("q", "")[:200]  # substring search
    return jsonify({"query": query, "results": _module_map().search(query)})


@component.route("/api/module-map/module/<string:module_type>")
@api_ratelimit
@login_required
def module_map_node(module_type):
    """
    One module in full: metadata, declared compatibility, how-to-run (the
    prerequisite chain + datasources + shape buckets) and available follow-ups.
    """
    info = _module_map().module(module_type)
    if info is None:
        return error(404, message="Module '%s' does not exist" % module_type)
    return jsonify(info)


@component.route("/api/module-map/graph")
@api_ratelimit
@login_required
def module_map_graph():
    """The whole graph as {nodes, edges} -- low-level/debug backbone."""
    return jsonify(_module_map().graph())
