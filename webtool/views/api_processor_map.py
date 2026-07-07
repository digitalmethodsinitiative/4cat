"""
Processor map API.

Thin JSON endpoints over `common.lib.processor_map` -- each just builds the
ProcessorMap and calls one method, so the data layer stays in common/lib and any
UI can be built against these without touching it.

Login-gated. Demonstrates what the declarative Compatibility specs make computable
(search, "how to run this", shape buckets, follow-ups) with no datasets and no
database.
"""
from flask import Blueprint, current_app, jsonify, request, g
from flask_login import login_required

from webtool.lib.helpers import error
from common.lib.processor_map import ProcessorMap

component = Blueprint("processormap", __name__)
api_ratelimit = current_app.limiter.shared_limit("3 per second", scope="api")

# Cache the built map per modules object. `g.modules` (app.fourcat_modules) is a
# single process-global, replaced only on a full reload, so its identity is a safe
# cache key -- a new identity forces a rebuild.
# NOTE: config is NOT part of the key: the ProcessorMap does not gate edges on
# per-user config today. Per-user maps would need the config (or user) in the key.
_MAP_CACHE = {}  # id(modules) -> (modules, ProcessorMap)


def _processor_map():
    modules = g.modules
    cached = _MAP_CACHE.get(id(modules))
    if cached is None or cached[0] is not modules:
        _MAP_CACHE.clear()
        _MAP_CACHE[id(modules)] = (modules, ProcessorMap(modules, g.config, logger=g.log))
    return _MAP_CACHE[id(modules)][1]


@component.route("/api/processor-map/catalogue")
@api_ratelimit
@login_required
def processor_map_catalogue():
    """Every processor with display metadata and flags (the browse surface)."""
    return jsonify({"processors": _processor_map().catalogue()})


@component.route("/api/processor-map/categories")
@api_ratelimit
@login_required
def processor_map_categories():
    """{category: [types]} for grouped browsing."""
    return jsonify(_processor_map().categories())


@component.route("/api/processor-map/search")
@api_ratelimit
@login_required
def processor_map_search():
    """Find processors by a substring of type/title/category/description."""
    query = request.args.get("q", "")[:200]  # substring search
    return jsonify({"query": query, "results": _processor_map().search(query)})


@component.route("/api/processor-map/processor/<string:processor_type>")
@api_ratelimit
@login_required
def processor_map_node(processor_type):
    """
    One processor in full: metadata, declared compatibility, how-to-run (the
    prerequisite chain + datasources + shape buckets) and available follow-ups.
    """
    info = _processor_map().processor(processor_type)
    if info is None:
        return error(404, message="Processor '%s' does not exist" % processor_type)
    return jsonify(info)


@component.route("/api/processor-map/graph")
@api_ratelimit
@login_required
def processor_map_graph():
    """The whole graph as {nodes, edges} -- low-level/debug backbone."""
    return jsonify(_processor_map().graph())
