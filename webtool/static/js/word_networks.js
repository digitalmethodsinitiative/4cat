var sigmaconfig = {
		defaultLabelColor: "#0e0e0e",
		defaultNodeColor: "#CE1B28",
		defaultEdgeColor: "#FFA5AC",
		enableHovering: false,
		strongGravityMode: true,
		defaultLabelAlignment: "right",
		minEdgeSize: 0.1,
		maxEdgeSize: 1,
		minNodeSize: 2,
		maxNodeSize: 20,
		labelThreshold: 1,
		verbose: true
}

var fa2config = {
	worker: true,
	barnesHutOptimize: false,
	//edgeWeightInfluence: 1,
	//scalingRatio: 1,
	startingIterations: 40,
	//strongGravityMode: true,
	slowDown: 1000
}

function init_network(core_json) {

	create_slider(Object.keys(core_json).length)
	render_new_network(core_json[Object.keys(core_json)[0]])

	// Notify what model is visualised here
	$("#alert-box").text("Model " + Object.keys(core_json)[0])
}

function render_new_network(json) {

	console.log(json)

	// Get the largest and smallest 
	var node_size_limits = get_size_limits(json["nodes"])
	var edge_size_limits = get_size_limits(json["edges"])

	s = new sigma({
		graph: json,
		container: "graph-container",
		settings: sigmaconfig
	})

	// Start the ForceAtlas2 algorithm on a new graph start
	$("#start-force").addClass("running")
	$("#start-force").text("Stop ForceAtlas2")
	$("#hourglass").show()

	s.startForceAtlas2(fa2config);

	// To render everything
	s.refresh()

}

function change_network(new_json) {
	/*
	Changes the network layout without rendering an entirely new graph.
	Also makes for nice transitions so graphs can be "animated".
	*/

	// Get data that's already in the graph
	var existing_nodes = s.graph.nodes()
	var existing_edges = s.graph.edges()
	var existing_nodes_ids = existing_nodes.map(value => value.id)
	var existing_edges_ids = existing_edges.map(value => value.id)

	// Keep track of the edges and nodes added to know what to remove afterwards
	var nodes_added = []
	var edges_added= []
	
	// Loop through new nodes
	for (var i = 0; i < new_json["nodes"].length; i++) {

		node = new_json["nodes"][i]
		nodes_added.push(node["id"])

		// If the node is not in the graph yet, add it!
		if (! existing_nodes_ids.includes(node["id"])) {
			
			s.graph.addNode({
				id: node["id"],
				size: node["size"],
				label: node["label"],
				x: (Math.random() * 20), // random between 0 and 20
				y: (Math.random() * 20),
				color: "#19B0A3"
			});
		}
		// If it's already in there, possibly change its attributes
		else {
			// Only size for now
			s.graph.nodes(node["id"]).size = parseFloat(node["size"])
			s.graph.nodes(node["id"]).color = "#CE1B28"
		}
	}

	// Loop through new edges
	for (var i = 0; i < new_json["edges"].length; i++) {

		edge = new_json["edges"][i]
		edges_added.push(edge["id"])

		// If the edge is not in the graph yet, add it!
		if (! existing_edges_ids.includes(edge["id"])) {
			s.graph.addEdge({
				id: edge["id"],
				label: edge["label"],
				size: edge["size"],
				source: edge["source"],
				target: edge["target"],
				color: "#FFA5AC",
			});
		}
		// If it's already in there, change its attributes
		else {
			// Only size for now
			s.graph.edges(edge["id"]).size = parseFloat(edge["size"])
		}
	}

	// Clean nodes and edges that are not in the new network
	for (node_id of existing_nodes_ids) {
		if (! nodes_added.includes(node_id)) {
			s.graph.dropNode(node_id) // also removes edges!
		}
	}

	s.refresh()
}

function create_slider(length) {
	// Creates an HTML slider based on the amount of w2v models returned from the server
	// Remove the old slider if it exists
	console.log("adding slider")
	$("#slider-container").empty()

	// Only add the slider if there"s multiple models
	if (length == 1) {
		$("#slider-container").html("")
	}
	else {
		notice = "<div class='control-panel-notice'>Slide to change date</div>"
		slider = "<div><input type='range' min='1' max='" + length + "' value='1' id='time-slider'></div>"
		animate_button = "<div><button id='btn-animate-slider'>Animate</button></div>"
		$('#slider-container').html(notice + slider + animate_button)
	}
}

function toggle_force_atlas() {
	/*
	Start/stop the ForceAtlas2 algorithm from running
	*/

	if ($("#start-force").hasClass("running")) {
		$("#start-force").removeClass("running")
		$("#start-force").text("Start ForceAtlas2")
		$("#hourglass").hide()
		s.stopForceAtlas2()
	}
	else {
		$("#start-force").addClass("running")
		$("#start-force").text("Stop ForceAtlas2")
		$("#hourglass").show()
		s.startForceAtlas2(fa2config);
	}
}

function change_date(index) {
	/*
	Change the nodes in the graph on the basis of a new object
	*/

	$("#alert-box").text("Date: " + Object.keys(core_json)[index])

	change_network(core_json[Object.keys(core_json)[index]])
}

function animate_networks(json) {
	/*
	Animate network animation
	*/

	console.log("Starting animation...")

	date_amount = Object.keys(json).length
	current_date = 0

	// Initiate new graphs every 3 seconds
	animate_network = setInterval(function() {
		// Trigger the slider to change
		change_date(current_date)
		$('#time-slider').attr("value", current_date + 1)
		current_date++
		if (current_date >= date_amount) {
			clearInterval(animate_network)
			
			}
		}, 3000)
	}


function get_size_limits(json) {
	/*
	Gets the minimum and maximum "size"
	and returns it as a tuple.
	*/

	// Take the first value as a starting point
	var min_size = parseFloat(json[0]["size"])
	var max_size = parseFloat(json[0]["size"])

	for (var i = 0; i < json.length; i++) {
		let size = parseFloat(json[i]["size"])
		if (size < min_size) {
			min_size = size
		}
		if (size > max_size) {
			max_size = size
		}
	}

	return [min_size, max_size]
}

/* Click handlers */

// ForceAtlas2 toggle button
$("#start-force").on("click", function(){
	toggle_force_atlas()
});

// Update the network if the slider changes
$("#slider-container").on("change", "#time-slider", function(){
	change_date((this.value - 1))
});

// Animate network animation
$("#slider-container").on("click", "#btn-animate-slider", function(){
	animate_networks(core_json)
});