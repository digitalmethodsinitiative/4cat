"""
Create a network of word relations.

The corresponding JavaScript file is found in webtool/static/js.
The corresponding CSS file is found in webtool/static/css.  

"""
import json
import unicodedata
import random

import config

from common.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

class SigmaNetwork(BasicProcessor):
	"""
	Generate a html page with a sigma js graph.
	"""

	type = "sigma-network"  # job type ID
	category = "Visualisation"  # category
	title = "Sigma js network"  # title displayed in UI
	description = "Visualise a gexf network in the browser with sigma js."  # description displayed in UI
	extension = "html"  # extension of result file, used internally and in UI

	@classmethod
	def is_compatible_with(cls, module=None):
		"""
		Allow processor on network files

		:param module: Dataset or processor to determine compatibility with
		"""
		return module.get_extension() in ["gexf"]

	def process(self):
		"""
		Create a HTML file with a network derived from a source_dataset dataset.

		"""

		# Get gexf or jdf data to use in the graph.
		# gdf and non-network files need to be parsed first.

		self.dataset.update_status("Generating HTML file")

		# We first need to make some changes to the NetworkX-generated gexf file
		# to make it compatible with sigma js. 
		sigma_gexf = self.render_gexf_sigma_compatible()

		# Generat the HTML page
		try:
			html_file = self.get_html_page(sigma_gexf)
		except MemoryError:
			self.dataset.update_status("Out of memory while processing network. Try downloading and visualising locally instead.", is_final=True)
			self.dataset.finish(0)
			return

		# Write HTML file
		with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
			output_file.write(html_file)

		# Finish
		self.dataset.update_status("Finished")
		self.dataset.finish(1)

	def render_gexf_sigma_compatible(self):
		"""
		Unfortunately sigma js does not unequivocally accept any gexf file.
		The gexf 1.2draft produced by networkx does not work by default./
		Luckily we only need to change one small thing: XXX
		"""

		with open(self.source_file, encoding="utf-8") as f:
			file_str = f.read()

		# A bit hacky: change gexf version from 1.2 to 1.3
		file_str = file_str.replace(
			'<gexf xmlns="http://www.gexf.net/1.2draft" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.gexf.net/1.2draft http://www.gexf.net/1.2draft/gexf.xsd" version="1.2">',
			'<gexf xmlns="http://www.gexf.net/1.3" version="1.3" xmlns:viz="http://www.gexf.net/1.3/viz" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.gexf.net/1.3 http://www.gexf.net/1.3/gexf.xsd">')

		# To make the gexf file sigma compatible, we need to add these viz tags
		file_str = file_str.replace("</node>", "<viz:size></viz:size>\n      <viz:position></viz:position>\n      </node>")
			
		# Give the nodes a random position by hard-coding it into the XML
		file_str = file_str.replace("{", "#!#_!#!").replace("}", "#@#_@#@")
		file_str = file_str.replace('<viz:position>', '<viz:position x="{}" y="{}">')
		position_count = file_str.count("{}")
		file_str = file_str.format(*(random.randint(-200, 200) for _ in range(position_count)))
		file_str = file_str.replace("#!#_!#!", "{").replace("#@#_@#@", "}")

		# Write HTML file
		sigma_gexf = self.dataset.get_results_path().with_suffix(".gexf")

		with open(sigma_gexf, "w", encoding="utf-8") as output_file:
			output_file.write(file_str)

		return sigma_gexf

	def get_html_page(self, source_file):
		"""
		Returns a html string with which a sigma graph can be displayed and manipulated.
		"""

		html_string = """
		<!DOCTYPE html>
		<html>
		<head>

			<title>Sigma js network</title>
			<meta content="text/html;charset=utf-8" http-equiv="Content-Type">
			<meta content="utf-8" http-equiv="encoding">

			<link rel="stylesheet" type="text/css" href="**server**static/css/sigma_network.css">

			<!-- Font Awesome -->
			<link href="**server**static/fontawesome/css/fontawesome.css" rel="stylesheet">
			<link href="**server**static/fontawesome/css/regular.css" rel="stylesheet">
			<link href="**server**static/fontawesome/css/solid.css" rel="stylesheet">
			<link href="**server**static/fontawesome/css/brands.css" rel="stylesheet">

			<!-- START SIGMA IMPORTS -->
			<script src="https://code.jquery.com/jquery-3.4.1.min.js" integrity="sha256-CSXorXvZcTkaix6Yvo6HppcZGetbYMGWSFlBw8HfCJo=" crossorigin="anonymous"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/sigma.core.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/conrad.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/utils/sigma.utils.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/utils/sigma.polyfills.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/sigma.settings.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/classes/sigma.classes.dispatcher.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/classes/sigma.classes.configurable.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/classes/sigma.classes.graph.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/classes/sigma.classes.camera.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/classes/sigma.classes.quad.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/classes/sigma.classes.edgequad.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/captors/sigma.captors.mouse.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/captors/sigma.captors.touch.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/sigma.renderers.canvas.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/sigma.renderers.webgl.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/sigma.renderers.svg.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/sigma.renderers.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/webgl/sigma.webgl.nodes.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/webgl/sigma.webgl.nodes.fast.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/webgl/sigma.webgl.edges.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/webgl/sigma.webgl.edges.fast.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/webgl/sigma.webgl.edges.arrow.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.labels.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.hovers.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.nodes.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edges.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edges.curve.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edges.arrow.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edges.curvedArrow.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edgehovers.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edgehovers.curve.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edgehovers.arrow.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.edgehovers.curvedArrow.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/canvas/sigma.canvas.extremities.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.utils.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.nodes.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.edges.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.edges.curve.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.labels.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/renderers/svg/sigma.svg.hovers.def.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/middlewares/sigma.middlewares.rescale.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/middlewares/sigma.middlewares.copy.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/misc/sigma.misc.animation.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/misc/sigma.misc.bindEvents.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/misc/sigma.misc.bindDOMEvents.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/src/misc/sigma.misc.drawHovers.js"></script>

			<script src="**server**static/js/sigma.js-1.2.1/plugins/sigma.layout.forceAtlas2/worker.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/plugins/sigma.layout.forceAtlas2/supervisor.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/plugins/sigma.exporters.svg/sigma.exporters.svg.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/plugins/sigma.plugins.filter/sigma.plugins.filter.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/plugins/sigma.parsers.gexf/gexf-parser.js"></script>
			<script src="**server**static/js/sigma.js-1.2.1/plugins/sigma.parsers.gexf/sigma.parsers.gexf.js"></script>

			<!-- END SIGMA IMPORTS -->

		</head>

		<body>

			<!-- Control panel -->
			<div id='control-panel'>

				<div id="network-name-box" class="control-panel-notice">
					Undefined network
				</div>
				

				<div id="main-alert-box" class="alert-box control-panel-notice"></div>

				<!-- slider for manipulating networks -->
				<!-- <div id="slider-container">
					<div class="control-panel-notice">
					Slide to change date.
						<div>
							<input id="time-slider" type="range" min="1" max="100" value="1">
						</div>
						<div>
							<button id="btn-animate-slider"><i  class="fa fa-spin fa-sync-alt invisible" ></i> <span class="button-text">Start animation</span></button>
						</div>
					</div>
				</div>
				-->
				<hr>

				<div id="parameter-alert-box" class="alert-box"></div>

				<div id="graph-manipulation">

					<!-- Settings ForceAtlas2 / gravity -->
					<div class="graph-manipulation-box" id="network-settings">
						<h2 class="graph-manipulation-box-header">Network settings</h2>
						<p>See the <a href="https://github.com/jacomyal/sigma.js/tree/master/plugins/sigma.layout.forceAtlas2" target="__blank">sigma js documentation</a> for parameter explanations.</p>

						<!-- Start / stop ForceAtlas2 -->
						<div class="graph-manipulation-subbox" id="start-force-container">
							<button id="start-force" class="standalone-button">
								<i id="hourglass" class='fa fa-spin fa-sync-alt invisible'></i> 
								<span class="button-text">Start ForceAtlas2</span>
							</button>
						</div>
						<!-- Other network settings -->
						<div class="graph-manipulation-subbox">
							<p><label for="gravity">Gravity: </label>
								<input class="parameter-input" id="gravity" name="gravity" type="number" min="1" value="1">
							</p>
							<p><label for="strong-gravity">Strong gravity: </label>
								<input class="parameter-input" id="strong-gravity" name="strong-gravity" type="checkbox">
							</p>
							<p><label for="edge-weight-influence">Edge weight influence: </label>
								<input class="parameter-input" id="edge-weight-influence" name="edge-weight-influence" type="number" min="0" value="0">
							</p>
							<p><label for="scaling-ratio">Scaling ratio: </label>
								<input class="parameter-input" id="scaling-ratio" name="scaling-ratio" type="number" min="1" value="1">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="linlog-mode">LinLog mode: </label>
								<input class="parameter-input" id="linlog-mode" name="linlog-mode" type="checkbox">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="outbound-attraction-distribution">Outbound Attraction Distribution: </label>
								<input class="parameter-input" id="outbound-attraction-distribution" name="outbound-attraction-distribution" type="checkbox">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="adjust-sizes">Adjust sizes: </label>
								<input class="parameter-input"id="adjust-sizes" name="adjust-sizes" type="checkbox"  value="">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="barnes-hut-optimise">Barnes-Hut optimise: </label>
								<input class="parameter-input" id="barnes-hut-optimise" name="barnes-hut-optimise" type="checkbox" checked>
							</p>
							<p><label for="barnes-hut-theta">Barnes-Hut theta: </label>
								<input class="parameter-input" id="barnes-hut-theta" name="barnes-hut-theta" type="number" min="0" value="0.5">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="slow-down">Slow down: </label>
								<input class="parameter-input" id="slow-down" name="slow-down" type="number" value="1">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="min-degree">Minimum degree: </label>
								<input class="parameter-input" id="min-degree" name="min-degree" type="number" value="1">
							</p>
						</div>

					</div>
					<hr>

					<!-- Visual settings -->
					<div class="graph-manipulation-box" id="visual-settings"></div>
						<h2 class="graph-manipulation-box-header">Visual</h2>
						<h3 class="graph-manipulation-box-header">Labels</h3>
						<div class="graph-manipulation-subbox">
							<p><label for="show-labels">Show labels: </label>
								<input class="parameter-input" id="show-labels" name="show-labels" type="checkbox" checked>
							</p>
							<p><label for="label-size">Label size: </label>
								<input class="parameter-input" id="label-size" name="label-size" type="number" min="1" value="14">
							</p>
							<p><label for="label-size-type">Size labels by node size: </label>
								<input class="parameter-input" id="label-size-type" name="label-size-type" type="checkbox">
							</p>
							<p><label for="label-threshold">Label threshold: </label>
								<input class="parameter-input" id="label-threshold" name="label-threshold" type="number" min="0.1" value="1">
							</p>
							<p><label for="label-colour">Label colour: </label>
								<input class="parameter-input" id="label-colour" name="label-colour" type="color" value="#00000">
							</p>
						</div>
						<h3 class="graph-manipulation-box-header">Nodes and edges</h3>
						<div class="graph-manipulation-subbox">
							<p><label for="min-node-size">Min node size: </label>
								<input class="parameter-input" id="min-node-size" name="min-node-size" type="number" min="0.1" value="1">
							</p>
							<p><label for="max-node-size">Max node size: </label>
								<input class="parameter-input" id="max-node-size" name="max-node-size" type="number" min="0.1" value="2">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="min-edge-size">Min edge size: </label>
								<input class="parameter-input" id="min-edge-size" name="min-edge-size" type="number" min="0.1" value="0.1">
							</p>
							<p><label for="max-edge-size">Max edge size: </label>
								<input class="parameter-input" id="max-edge-size" name="max-edge-size" type="number" min="0.1" value="1">
							</p>
						</div>
						<div class="graph-manipulation-subbox">
							<p><label for="node-colour">Node colour: </label>
								<input class="parameter-input" id="node-colour" name="node-colour" type="color" value="#CE1B28">
							</p>
							<p><label for="edge-colour">Edge colour: </label>
								<input class="parameter-input" id="edge-colour" name="edge-colour" type="color" value="#FFA5AC">
							</p>
						</div>
					</div>
					<hr>
					<div class="graph-manipulation-box" id="visual-settings">
						<h2 class="graph-manipulation-box-header">Save to svg</h2>
						<p>
							<input class="parameter-input full-width" id="file-name" name="file-name" type="text" placeholder="sigma-graph.svg">
						</p>
						<button id="save-svg" class="standalone-button">
							<span class="button-text">Download</span>
						</button>
					</div>
				</div>

			</div>

			<div id="footer">
				<p>Made with <a href='https://archive.4plebs.org' target='_blank'>4CAT</a> and <a href="https://github.com/jacomyal/sigma.js">sigma js</a>.</p>
			</div>

			<!-- Where the network graph will be -->
			<div id="graph-container">
			</div>

			<!-- 4CAT JavaScript -->
			<script src="**server**static/js/sigma_network.js" charset="utf-8"></script>

			<script type="text/javascript">

				// Initialise the graph
				$(document).ready(function(){
					init_network("**source_file**");
				});

			</script>

		</body>
		</html>
		"""

		server_url = "https" if config.FlaskConfig.SERVER_HTTPS else "http"
		server_url += "://%s" % config.FlaskConfig.SERVER_NAME

		if not server_url.endswith("/"):
			server_url += "/"

		# We need to ensure this is a relative path, else we'll get same-origin shenanigans
		source_file = "/result/" + source_file.name
		return html_string.replace("**server**", server_url).replace("**source_file**", source_file)