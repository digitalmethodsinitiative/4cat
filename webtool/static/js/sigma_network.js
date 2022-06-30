import * as color from './color.js';
import {hsv2rgb, rgb2hsv} from "./color.js";

const forceatlas2 = graphologyLibrary.layoutForceAtlas2;
const circlepack = graphologyLibrary.layout.circlepack;
const fa2worker = graphologyLibrary.FA2Layout;
const palette = ["#0274e1", "#8fbd35", "#fe80ec", "#00aa4e", "#820017", "#00760e", "#c14218", "#ffac42"]
const gradient = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0].map((fraction) => {
    let base = rgb2hsv(206, 27, 40);  // 4cat red
    base[1] = fraction;
    return 'rgb(' + hsv2rgb(...base).map(v => parseInt(v)).join(', ') + ')';
});
console.log(gradient);

const sigma_graph = {
    graph: null,
    sigma: null,
    stats: {},
    top_communities: null,
    attribute_map: {},

    map_attribute: function (attribute) {
        let values = {};
        sigma_graph.graph.nodes().map((node) => {
            let value = sigma_graph.graph.getNodeAttribute(node, attribute);
            if (!(value in values)) {
                values[value] = 0;
            }
            values[value] += 1;
        });

        // I hate javascript
        let value_count = [...Object.values(values)];
        value_count = value_count.sort((a, b) => a - b).reverse().slice(0, palette.length);
        let top_values = []
        let min_size = value_count.pop();
        for (let num in values) {
            if (values[num] >= min_size) {
                top_values.push(String(num));
            }
        }
        sigma_graph.attribute_map[attribute] = top_values.slice(0, palette.length);
    },

    init: function () {
        let container = document.querySelector('#graph-container');
        let source = container.getAttribute('data-source');

        fetch(source)
            .then((res) => res.text())
            .then((gexf) => {
                // Parse GEXF string:
                sigma_graph.graph = graphologyLibrary.gexf.parse(graphology.Graph, gexf);

                graphologyLibrary.layout.random.assign(sigma_graph.graph);
                let degrees = sigma_graph.graph.nodes().map(function (n) {
                    return sigma_graph.graph.degree(n);
                });
                sigma_graph.stats.max_degree = Math.max(...degrees);
                sigma_graph.stats.min_degree = Math.min(...degrees);
                graphologyLibrary.communitiesLouvain.assign(sigma_graph.graph, {resolution: 1});
                this.map_attribute('community');

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

                        if (document.querySelector('#label-size-type').checked) {
                            let range = size * 3;
                            let ratio = (data.degree - sigma_graph.stats.min_degree) / (sigma_graph.stats.max_degree - sigma_graph.stats.min_degree);
                            size += (ratio * range);
                        }

                        context.font = `${weight} ${size}px sans-serif`;
                        context.fillStyle = color;
                        context.fillText(data.label, data.x + data.size + 3, data.y + size / 3);
                    },
                    nodeReducer: function (node, data) {
                        let mode = document.getElementById('node-colouring').value;
                        let threshold = parseFloat(document.querySelector('#min-degree').value);
                        let degree = sigma_graph.graph.degree(node);
                        threshold = sigma_graph.stats.min_degree + ((sigma_graph.stats.max_degree - sigma_graph.stats.min_degree) * threshold);
                        if (degree < threshold) {
                            data.color = 'rgba(0, 0, 0, 255)';
                        } else if (mode.indexOf('attribute-') === 0) {
                            let attribute = mode.split('attribute-').pop();
                            if (!(attribute in sigma_graph.attribute_map)) {
                                sigma_graph.map_attribute(attribute);
                            }
                            let value = String(data[attribute]);
                            let index = sigma_graph.attribute_map[attribute].indexOf(value);
                            if (index !== -1) {
                                console.log(palette[value])
                                data.color = palette[index];
                            } else {
                                data.color = 'rgb(192, 192, 192)';
                            }
                        } else if (mode === 'degree') {
                            let ratio = (degree - sigma_graph.stats.min_degree) / (sigma_graph.stats.max_degree - sigma_graph.stats.min_degree);
                            let index = Math.round(ratio * gradient.length);
                            console.log(gradient[index]);
                            data.color = gradient[index];
                        }
                        data.degree = degree;
                        return data;
                    }
                });

                sigma_graph.register_handlers();
            });
    },

    register_handlers: function () {
        document.getElementById('start-layout').addEventListener('click', sigma_graph.layout.toggle);
        document.querySelectorAll('#network-settings input').forEach(function (control) {
            control.addEventListener('input', sigma_graph.fa2.update_settings);
        })

        document.getElementById('graph-layout').addEventListener('input', sigma_graph.layout.change);

        document.querySelectorAll('#visual-settings input, #visual-settings select').forEach(function (control) {
            control.addEventListener('input', sigma_graph.update_visual_settings);
        })

        // figure out categories we can colour by
        let extra_categories = [];
        sigma_graph.graph.forEachNode((node) => {
            let attributes = sigma_graph.graph.getNodeAttributes(node);
            for (let attribute in attributes) {
                if (['label', 'x', 'y', 'community'].indexOf(attribute) === -1 && extra_categories.indexOf(attribute) === -1) {
                    extra_categories.push(attribute);
                }
            }
        });
        extra_categories.forEach((category) => {
            let option = document.createElement('option');
            option.setAttribute('value', 'attribute-' + category);
            option.innerText = 'Node attribute: ' + category;
            document.getElementById('node-colouring').appendChild(option);
        })


        sigma_graph.update_visual_settings();
    },

    update_visual_settings: function () {
        sigma_graph.sigma.setSetting("labelRenderedSizeThreshold", document.getElementById('label-threshold').value);
        //sigma_graph.sigma.setSetting("labelSize", document.querySelector('#label-size').value);
        sigma_graph.sigma.setSetting("labelColor", {color: document.getElementById('label-colour').value});

        // node sizes
        let min_size = parseFloat(document.getElementById('min-node-size').value);
        let max_size = parseFloat(document.getElementById('max-node-size').value);
        sigma_graph.graph.forEachNode((node) => {
            let degree = sigma_graph.graph.degree(node);
            let range = max_size - min_size;
            let ratio = (degree - sigma_graph.stats.min_degree) / (sigma_graph.stats.max_degree - sigma_graph.stats.min_degree);
            let size = min_size + (ratio * range);
            sigma_graph.graph.setNodeAttribute(node, "size", size,);
        });

        let show_edges = document.getElementById('show-edges').checked;
        let edge_colour = show_edges ? document.getElementById('edge-colour').value : 'rgba(0, 0, 0, 255)';
        sigma_graph.sigma.setSetting("defaultEdgeColor", edge_colour);

        let show_nodes = document.getElementById('show-nodes').checked;
        let node_color = show_nodes ? document.getElementById('node-colour').value : 'rgba(0, 0, 0, 255)';
        sigma_graph.sigma.setSetting("defaultNodeColor", node_color);

        sigma_graph.sigma.refresh();
    },

    layout: {
        layout: 'fa2',

        toggle: function () {
            sigma_graph[sigma_graph.layout.layout].toggle();
        },

        change: function () {
            let choice = document.getElementById('graph-layout').value;
            if (choice !== sigma_graph.layout.layout) {
                if (sigma_graph[sigma_graph.layout.layout].hasOwnProperty('uninit')) {
                    sigma_graph[sigma_graph.layout.layout].uninit();
                }
                document.querySelectorAll('.layout-parameters').forEach((element) => {
                    if (element.getAttribute('data-layout') !== choice) {
                        element.style.display = 'none';
                    } else {
                        element.style.display = 'block';
                    }
                });
                sigma_graph.layout.layout = choice;
                sigma_graph[choice].init();
            }

        }
    },

    noverlap: {},

    circlepack: {
        have_init: false,
        continuous: false,

        init: function () {
            document.querySelector('#start-layout span').innerHTML = '<i class="fa fa-shapes"></i> Apply Circle Pack';
        },

        toggle: function () {
            circlepack.assign(sigma_graph.graph, {
                hierarchyAttributes: ['degree', 'community']
            });
        }
    },

    fa2: {
        have_init: false,
        layout: null,
        continuous: true,

        init: function () {
            const settings = forceatlas2.inferSettings(sigma_graph.graph);
            sigma_graph.fa2.layout = new fa2worker(sigma_graph.graph, {
                settings: sigma_graph.fa2.get_settings()
            });
            sigma_graph.fa2.have_init = true;
            document.querySelector('#start-layout span').innerHTML = '<i class="fa fa-play"></i> Start ForceAtlas2';
        },

        start: function () {
            if (!sigma_graph.fa2.have_init) {
                sigma_graph.fa2.init();
            }

            sigma_graph.fa2.layout.start();
            document.querySelector('#start-layout span').innerHTML = '<i class="fa fa-sync fa-spin"></i> Stop ForceAtlas2';
        },

        stop: function () {
            sigma_graph.fa2.layout.stop();
            document.querySelector('#start-layout span').innerHTML = '<i class="fa fa-play"></i> Start ForceAtlas2';
        },

        toggle: function () {
            if (sigma_graph.fa2.layout && sigma_graph.fa2.layout.isRunning()) {
                sigma_graph.fa2.stop();
            } else {
                sigma_graph.fa2.start();
            }
        },

        uninit: function () {
            if (sigma_graph.fa2.have_init) {
                sigma_graph.fa2.layout.kill();
                sigma_graph.fa2.have_init = false;
            }
        },

        update_settings() {
            if (!sigma_graph.fa2.have_init) {
                sigma_graph.fa2.init();
            }

            let is_running = sigma_graph.fa2.layout.isRunning();

            sigma_graph.fa2.uninit();

            if (is_running) {
                sigma_graph.fa2.start();
            } else {
                sigma_graph.fa2.init();
            }
        },

        get_settings: function () {
            return {
                adjustSizes: document.getElementById('adjust-sizes').checked,
                barnesHutOptimize: document.getElementById('barnes-hut-optimise').checked,
                barnesHutTheta: parseFloat(document.getElementById('barnes-hut-theta').value),
                edgeWeightInfluence: parseFloat(document.getElementById('edge-weight-influence').value),
                gravity: parseFloat(document.getElementById('gravity').value),
                linLogMode: document.getElementById('linlog-mode').checked,
                outboundAttractionDistribution: document.getElementById('outbound-attraction-distribution').checked,
                scalingRatio: parseFloat(document.getElementById('scaling-ratio').value),
                slowDown: parseFloat(document.getElementById('slow-down').value),
                strongGravityMode: document.getElementById('strong-gravity').checked
            }
        }
    }
}

if (document.readyState !== 'loading') {
    sigma_graph.init();
} else {
    document.addEventListener('DOMContentLoaded', sigma_graph.init);
}