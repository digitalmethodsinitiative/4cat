"""
OpenAPI specification generator for Flask-based APIs

Usage:

- Instantiate an OpenAPICollector instance in the Flask app's __init__.py:
      openapi = OpenAPICollector(app)  # app being the Flask app

- Import the instance in the view definition file(s):
      from [flask-app-name] import openapi

- Decorate endpoint routes with the collector decorator:
      @openapi.endpoint
      def some_route():

- Add a route (or other output method) for the generated specification in which
  the following call returns a dictionary representing the OpenAPI
  specification tree:
      return json.dumps(openapi.generate())
"""
import inspect
import re


class OpenAPICollector:
	"""
	Flask-compatible OpenAPI generator
	"""
	endpoints = {}
	flask_app = None
	type_map = {"int": "integer", "str": "string"}  # openapi is picky about type names

	def __init__(self, app):
		"""
		Store a reference to the used Flask app

		This is used to later inspect the available routes and extract endpoint
		metadata from them.

		:param app:  Flask app
		"""
		self.flask_app = app

	def endpoint(self, callback):
		"""
		Mark as OpenAPI endpoint

		Decorator that marks a route as an endpoint that should be documented
		in the OpenAPI specification.

		:param callback:  Route view function
		:return:  The same function, but meanwhile the function metadata has
		          been stored to be integrated in the OpenAPI spec later.
		"""

		collapse_whitespace = re.compile(r"\s+")
		if callback.__doc__:
			# if there is a docstring, we can get most metadata about the
			# endpoint from there

			# extract first paragraph of docstring as endpoint title
			docstring = inspect.cleandoc(callback.__doc__).strip()
			elements = re.split(r"(\n\s*\n)", docstring)
			title = elements[0].strip()

			# split remaining docstring in description and structured metadata
			docbits = re.split(r"(\n\s*:)", "".join(elements[1:]))
			description = docbits[0].strip()
			metadata = "".join(docbits[1:])

			# extract definitions of http request parameters
			request_vars = {var[0].split(" ").pop(): {"name": var[0].strip(), "description": var[1].strip()} for var in
							re.findall(r":request-param ([^:]+):([^:]+)", metadata)}

			# clean http request metadata
			for name in request_vars:
				var_definition = request_vars[name]["name"].split(" ")
				request_vars[name]["type"] = var_definition[0] if len(var_definition) > 1 else "string"
				request_vars[name]["type"] = self.type_map.get(request_vars[name]["type"], request_vars[name]["type"])
				request_vars[name]["name"] = var_definition.pop()
				request_vars[name]["in"] = "request"
				request_vars[name]["description"] = collapse_whitespace.sub(" ", request_vars[name]["description"])

				# optional parameters are marked by a ? before the parameter name
				if request_vars[name]["name"][0] == "?":
					request_vars[name]["required"] = False
					request_vars[name]["name"] = request_vars[name]["name"][1:].strip()
				else:
					request_vars[name]["required"] = True

			# extract definitions of function parameters
			rest_keywords = "param|parameter|arg|argument|key|keyword"
			vars = {var[1].strip().split(" ").pop(): {"name": var[1].strip(), "description": var[2].strip()} for var in
					re.findall(r":(" + rest_keywords + ") ([^:]+):([^:]+)", metadata)}

			# clean var metadata
			for name in vars:
				var_definition = vars[name]["name"].split(" ")
				vars[name]["type"] = var_definition[0].strip() if len(var_definition) > 1 else "string"
				vars[name]["type"] = self.type_map.get(vars[name]["type"], vars[name]["type"])
				vars[name]["name"] = var_definition.pop()
				vars[name]["description"] = collapse_whitespace.sub(" ", vars[name]["description"])

			# see if the mime type of the outcome has been defined
			mime = re.search(r":rmime:([^:]+)", metadata)
			mime = mime[1].strip() if mime else "application/json"

		else:
			# if there is no docstring (shame!) assume defaults
			docstring = ""
			vars = request_vars = {}
			title = description = ""
			mime = "application/json"

		# Use return description as endpoint data summary
		result = re.search(r":(return|returns)[^:]*:([^:]+)", docstring)
		if result and result[2].strip():
			result = collapse_whitespace.sub(" ", result[2].strip())
		else:
			# captain obvious to the rescue
			result = "Query result"

		# store endpoint metadata for later use
		self.endpoints[callback.__name__] = {
			"method": "get",
			"title": title,
			"description": collapse_whitespace.sub(" ", description),
			"mime": mime,
			"return": result,
			"vars": vars,
			"request-vars": request_vars
		}

		# return the original function, unchanged
		return callback

	def generate(self):
		"""
		Generate OpenAPI API specification

		Loops through all Flask endpoints that are registered and for all of
		those that are marked as being an endpoint, adds them to the OpenAPI
		output, which is then written to a file.

		This method should be called once Flask has finished initialisation; a
		good way to do this is calling it via the `before_first_request`
		decorator.

		The OpenAPI description and definition of the decorated functions is
		built from their docstring. The parser assumes a reST-formatted
		docstring.

		:return dict: The OpenAPI-formatted specification, as a dictionary
		              that can be (f.ex.) dumped as JSON for a usable spec.
		"""
		spec = {
			"swagger": "2.0",
			"info": {
				"title": "4CAT: Capture and Analysis Toolkit RESTful API",
				"version": "v1"
			},
			"paths": {
			}
		}

		var_regex = re.compile(r"<([^>]+)>")

		# loop through available routes in Flask app
		for rule in self.flask_app.url_map.iter_rules():
			# check if this route is marked as an API endpoint
			endpoint = rule.endpoint
			rule_func = self.flask_app.view_functions[endpoint].__name__
			if rule_func not in self.endpoints:
				continue

			pointspec = self.endpoints[rule_func]

			# find parameters in endpoint path
			vars = {}
			for var in var_regex.findall(rule.rule):
				var = var.split(":")
				if len(var) == 1:
					# by default, take docstring typehint or assume string
					if var[0] in pointspec["vars"]:
						vars[var[0]] = pointspec["vars"][var[0]]["type"]
					vars[var[0]] = "string"
				else:
					# if given, take type from path (overrides docstring)
					vars[var[1]] = self.type_map.get(var[0], var[0])

			# OpenAPI spec mandates { instead of < but otherwise identical to WZ routes
			path = re.sub(r"<[^:>]+:([^>]+)>", r"<\1>", rule.rule).replace("<", "{").replace(">", "}")
			pointspec = self.endpoints[endpoint]

			# add paths to spec
			spec["paths"][path] = {
				method.lower(): {
					"operationId": rule_func,  # use function name as endpoint ID
					"description": pointspec["title"],
					"summary": pointspec["description"],
					"produces": [
						pointspec["mime"]
					],
					# we cannot cope with other response codes, unfortunately
					"responses": {
						"200": {
							"description": pointspec["return"]
						}
					},
					# combine path parameters and any request parameters found in docstring
					"parameters": [{
						"name": var,
						"in": "path",
						"required": True,
						"description": pointspec["vars"][var]["description"] if var in pointspec["vars"] else var,
						"type": vars[var]
					} for var in vars] + [{
						"name": request_var["name"],
						"in": "request",
						"required": request_var["required"],
						"description": request_var["description"],
						"type": request_var["type"]
					} for request_var in pointspec["request-vars"].values()]
				} for method in rule.methods if method in ("GET", "POST", "PUT", "DELETE")}  # RESTful methods only

			# return a dictionary that can (should) be json'ed or yaml'ed
		return spec
