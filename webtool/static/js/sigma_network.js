const forceatlas2 = graphologyLibrary.layoutForceAtlas2;
const fa2worker = graphologyLibrary.FA2Layout;

const sigma_graph = {
    graph: null,
    sigma: null,
    stats: {},

    init: function () {
        let container = document.querySelector('#graph-container');
        let source = container.getAttribute('data-source');

        fetch(source)
            .then((res) => res.text())
            .then((gexf) => {
                // Parse GEXF string:
                sigma_graph.graph = graphologyLibrary.gexf.parse(graphology.Graph, gexf);

                graphologyLibrary.layout.random.assign(sigma_graph.graph);
                let degrees = sigma_graph.graph.nodes().map(function(n) { return sigma_graph.graph.degree(n); });
                sigma_graph.stats.max_degree = Math.max(...degrees);
                sigma_graph.stats.min_degree = Math.min(...degrees);

                sigma_graph.sigma = new Sigma(sigma_graph.graph, container, {
                    minCameraRatio: 0.1,
                    maxCameraRatio: 10,
                    labelRenderedSizeThreshold: 1,
                    labelRenderer: function drawLabel(context, data, settings) {
                        if (!data.label) return;

                        let size = settings.labelSize,
                            font = settings.labelFont,
                            weight = settings.labelWeight,
                            color = settings.labelColor.color;

                        if(document.querySelector('#label-size-type').checked) {
                            let range = size * 3;
                            let ratio = (data.degree - sigma_graph.stats.min_degree) / (sigma_graph.stats.max_degree - sigma_graph.stats.min_degree);
                            size += (ratio * range);
                        }

                        context.font = `${weight} ${size}px ${font}`;
                        const width = context.measureText(data.label).width + 8;

                        context.fillStyle = "#ffffffcc";
                        context.fillRect(data.x + data.size, data.y + size / 3 - 15, width, 20);

                        context.fillStyle = color;
                        context.fillText(data.label, data.x + data.size + 3, data.y + size / 3);
                    },
                    nodeReducer: function(node, data) {
                        let threshold = parseFloat(document.querySelector('#min-degree').value);
                        let degree = sigma_graph.graph.degree(node);
                        threshold = sigma_graph.stats.min_degree + ((sigma_graph.stats.max_degree - sigma_graph.stats.min_degree) * threshold);
                        if(degree < threshold) {
                            data.color = 'rgba(0, 0, 0, 255)';
                        }
                        data.degree = degree;
                        return data;
                    }
                });

                sigma_graph.register_handlers();
            });
    },

    register_handlers: function () {
        document.querySelector('#start-force').addEventListener('click', sigma_graph.fa2.toggle);
        document.querySelectorAll('#network-settings input').forEach(function (control) {
            control.addEventListener('input', sigma_graph.fa2.update_settings);
        })

        document.querySelectorAll('#visual-settings input').forEach(function (control) {
            control.addEventListener('input', sigma_graph.update_visual_settings);
        })

        sigma_graph.update_visual_settings();
    },

    update_visual_settings: function() {
        sigma_graph.sigma.setSetting("labelRenderedSizeThreshold", document.querySelector('#label-threshold').value);
        //sigma_graph.sigma.setSetting("labelSize", document.querySelector('#label-size').value);
        sigma_graph.sigma.setSetting("labelColor", { color: document.querySelector('#label-colour').value});

        // node sizes
        let min_size = parseFloat(document.querySelector('#min-node-size').value);
        let max_size = parseFloat(document.querySelector('#max-node-size').value);
        sigma_graph.graph.forEachNode((node) => {
            let degree = sigma_graph.graph.degree(node);
            let range = max_size - min_size;
            let ratio = (degree - sigma_graph.stats.min_degree) / (sigma_graph.stats.max_degree - sigma_graph.stats.min_degree);
            let size = min_size + (ratio * range);
            sigma_graph.graph.setNodeAttribute(node, "size", size,);
        });

        let show_edges = document.querySelector('#show-edges').checked;
        let edge_colour = show_edges ? document.querySelector('#edge-colour').value : 'rgba(0, 0, 0, 255)';
        sigma_graph.sigma.setSetting("defaultEdgeColor", edge_colour);

        let show_nodes = document.querySelector('#show-nodes').checked;
        let node_color = show_nodes ? document.querySelector('#node-colour').value : 'rgba(0, 0, 0, 255)';
        sigma_graph.sigma.setSetting("defaultNodeColor", node_color);

        sigma_graph.sigma.refresh();
    },

    fa2: {
        have_init: false,
        layout: null,

        init: function () {
            const settings = forceatlas2.inferSettings(sigma_graph.graph);
            sigma_graph.fa2.layout = new fa2worker(sigma_graph.graph, {
                settings: sigma_graph.fa2.get_settings()
            });
            sigma_graph.fa2.have_init = true;
        },

        start: function () {
            if (!sigma_graph.fa2.have_init) {
                sigma_graph.fa2.init();
            }

            sigma_graph.fa2.layout.start();
            document.querySelector('#start-force span').innerHTML = '<i class="fa fa-sync fa-spin"></i> Stop ForceAtlas2';
        },

        stop: function () {
            sigma_graph.fa2.layout.stop();
            document.querySelector('#start-force span').innerHTML = '<i class="fa fa-play"></i> Start ForceAtlas2';
        },

        toggle: function () {
            if (sigma_graph.fa2.layout && sigma_graph.fa2.layout.isRunning()) {
                sigma_graph.fa2.stop();
            } else {
                sigma_graph.fa2.start();
            }
        },

        update_settings() {
            if (!sigma_graph.fa2.have_init) {
                sigma_graph.fa2.init();
            }

            let is_running = sigma_graph.fa2.layout.isRunning();

            sigma_graph.fa2.layout.kill();
            sigma_graph.fa2.have_init = false;

            if (is_running) {
                sigma_graph.fa2.start();
            } else {
                sigma_graph.fa2.init();
            }
        },

        get_settings: function () {
            return {
                adjustSizes: document.querySelector('#adjust-sizes').checked,
                barnesHutOptimize: document.querySelector('#barnes-hut-optimise').checked,
                barnesHutTheta: parseFloat(document.querySelector('#barnes-hut-theta').value),
                edgeWeightInfluence: parseFloat(document.querySelector('#edge-weight-influence').value),
                gravity: parseFloat(document.querySelector('#gravity').value),
                linLogMode: document.querySelector('#linlog-mode').checked,
                outboundAttractionDistribution: document.querySelector('#outbound-attraction-distribution').checked,
                scalingRatio: parseFloat(document.querySelector('#scaling-ratio').value),
                slowDown: parseFloat(document.querySelector('#slow-down').value),
                strongGravityMode: document.querySelector('#strong-gravity').checked
            }
        }
    }
}

if (document.readyState !== 'loading') {
    sigma_graph.init();
} else {
    document.addEventListener('DOMContentLoaded', sigma_graph.init);
}