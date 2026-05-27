"""
Map-item API endpoint - allows running a datasource's map_item function
against a single submitted item via HTTP.

Used by external tools (like Zeeschuimer) to validate that auto-generated
map_item translations produce the same output as the Python original.
"""

import json
import traceback
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, g
from flask_login import login_required

from webtool.lib.helpers import error
from common.lib.exceptions import MapItemException
from common.lib.item_mapping import MissingMappedField, MappedItem
from common.lib.helpers import format_import_item


component = Blueprint("map_item", __name__)
api_ratelimit = current_app.limiter.shared_limit("100 per minute", scope="api")


def _get_search_class(modules, datasource_id):
	"""
	Look up the search/import class for a datasource.

	Abstracts the ModuleCollector convention where worker keys append a suffix
	to the datasource ID. Most use `-search`, some (e.g. twitter-import) use
	`-import`. Returns None if no matching worker is found.

	TODO: ModuleCollector should expose this directly.
	"""
	return (
		modules.workers.get(f"{datasource_id}-search")
		or modules.workers.get(f"{datasource_id}-import")
	)


@component.route("/api/datasources/")
@api_ratelimit
@current_app.openapi.endpoint("map_item")
def list_datasources():
	"""
	List all available datasources with map_item support.

	Returns all datasources that have a map_item function, including a flag
	indicating if they're from Zeeschuimer. Caller can filter as needed.

	:return: JSON object with array of datasource metadata

	:return-schema: {
		type=object,
		properties={
			datasources={
				type=array,
				items={
					type=object,
					properties={
						id={type=string},
						name={type=string},
						has_map_item={type=boolean},
						is_from_zeeschuimer={type=boolean}
					}
				}
			}
		}
	}
	"""
	
	available = []
	for datasource_id, metadata in g.modules.datasources.items():
		search_class = _get_search_class(g.modules, datasource_id)
		if not search_class:
			continue

		available.append({
			"id": datasource_id,
			"name": metadata.get("name", datasource_id),
			"is_from_zeeschuimer": getattr(search_class, "is_from_zeeschuimer", False),
			"has_map_item": hasattr(search_class, "map_item") and callable(getattr(search_class, "map_item"))
		})

	return jsonify({
		"datasources": sorted(available, key=lambda x: x["id"])
	}), 200


class MissingMappedFieldEncoder(json.JSONEncoder):
	"""Custom JSON encoder to serialize MissingMappedField objects."""

	def default(self, obj):
		if isinstance(obj, MissingMappedField):
			return {
				"__missing": True,
				"value": obj.value
			}
		return super().default(obj)


@component.route("/api/map-item/<string:datasource_id>/", methods=["POST"])
@api_ratelimit
@login_required
@current_app.openapi.endpoint("map_item")
def map_item_endpoint(datasource_id):
	"""
	Run a datasource's map_item function against a single item.

	Used by external tools (e.g. Zeeschuimer's test runner) to validate that
	an auto-generated JS port of `map_item` produces the same output as the
	Python original.

	The submitted item is passed through `format_import_item` first, matching
	the transformation applied during normal NDJSON imports, so the endpoint
	exercises the same code path as production imports.

	Distinguishes three outcomes:
	- `mapped`: map_item returned successfully
	- `skipped`: map_item raised MapItemException (intentional skip)
	- `error`: map_item raised an unexpected exception (bug or bad data)

	Authenticate via the `Authentication` header or `?access-token` query
	parameter using a 4CAT access token.

	:param datasource_id: The datasource identifier (e.g., "tiktok", "instagram")
	:request-body item: Zeeschuimer-format item with a `data` field

	:return: JSON response. One of:
	- `{status: "mapped", item: {...}}`
	- `{status: "skipped", reason: "..."}`
	- `{status: "error", message: "..."}`

	:return-schema: {
		type=object,
		properties={
			status={
				type=string,
				enum=["mapped", "skipped", "error"]
			}
		},
		required=["status"]
	}
	"""
	# Validate request body
	body = request.get_json(silent=True)
	if body is None:
		return error(400, error="Request body must be valid JSON")
	if "item" not in body:
		return error(400, error="Request body must contain an 'item' field")
	zeeschuimer_item = body["item"]
	if not isinstance(zeeschuimer_item, dict):
		return error(400, error="'item' field must be a JSON object")

	# Look up the datasource's search class
	search_class = _get_search_class(g.modules, datasource_id)
	if search_class is None:
		return error(404, error=f"Unknown datasource: {datasource_id}")
	if not (hasattr(search_class, "map_item") and callable(getattr(search_class, "map_item"))):
		return error(404, error=f"Datasource '{datasource_id}' does not implement map_item")

	# Wrap item (mirrors the NDJSON import path)
	wrapped_item = format_import_item(zeeschuimer_item)

	# Call map_item directly; going through get_mapped_item would wrap 
	# KeyError/IndexError and accidental errors would be skiped.
	try:
		mapped_item = search_class.map_item(wrapped_item)
	except MapItemException as e:
		# Intentional skip (e.g. Instagram ad detection)
		return jsonify({
			"status": "skipped",
			"reason": str(e)
		}), 200
	except Exception as e:
		# Unexpected error — point at the deepest frame for debugging
		tb_frames = traceback.extract_tb(e.__traceback__)
		frame = tb_frames[-1] if tb_frames else None
		location = f" at {Path(frame.filename).name}:{frame.lineno}" if frame else ""
		g.log.warning(f"map_item error for {datasource_id}: {traceback.format_exc()}")
		return jsonify({
			"status": "error",
			"message": f"{type(e).__name__}: {e}{location}"
		}), 200

	# Unwrap MappedItem if returned; otherwise treat as plain dict
	if isinstance(mapped_item, MappedItem):
		item_data = mapped_item.get_item_data(safe=False)
	else:
		item_data = mapped_item

	# Use the custom encoder to preserve MissingMappedField as a tagged object
	response_data = json.loads(json.dumps(item_data, cls=MissingMappedFieldEncoder))

	return jsonify({
		"status": "mapped",
		"item": response_data
	}), 200
