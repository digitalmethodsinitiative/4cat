var process = function (json) {
    var x = 0,
        r = Raphael("chart", json.buckets.length * 110, 700),
        labels = {},
        textattr = {"font": '11px', stroke: "none", fill: "#000"},
        paths = {}


    // Set viewbox of graphic
    r.setViewBox(-30,-30, json.buckets.length * 110, 700, true)

    function finishes() {
        for (var i in json.labels) {
            var start, end;

            // Check the end for each entry(?)
            for (var j = json.buckets.length - 1; j >= 0; j--) {
                var isin = false;
                // Match bucket ints names with label dicts(?)
                for (var k = 0, kk = json.buckets[j].i.length; k < kk; k++) {
                    isin = isin || (json.buckets[j].i[k][0] == i);
                }
                // Stop when the last label is reached(?)
                if (isin) {
                    end = j;
                    break;
                }
            }

            // Check the start of the entries(?)
            for (var j = 0, jj = json.buckets.length; j < jj; j++) {
                var isin = false;
                for (var k = 0, kk = json.buckets[j].i.length; k < kk; k++) {
                    isin = isin || (json.buckets[j].i[k][0] == i);
                };
                if (isin) {
                    start = j;
                    break;
                }
            }

            // Check if the entry is in one of the next buckets(?)
            for (var j = start, jj = end; j < jj; j++) {
                var isin = false;
                for (var k = 0, kk =  json.buckets[j].i.length; k < kk; k++) {
                    isin = isin || (json.buckets[j].i[k][0] == i);
                }
                if (!isin) {
                    json.buckets[j].i.push([i, 0]);
                }
            }
        }
    }

    function block() {
        var p, h;
        finishes();
        for (var j = 0, jj = json.buckets.length; j < jj; j++) {
            var flows = json.buckets[j].i;
            h = 0;
            for (var i = 0, ii = flows.length; i < ii; i++) {
                p = paths[flows[i][0]];
                if (!p) {
                    p = paths[flows[i][0]] = {f:[], b:[]};
                }
                p.f.push([x, h, flows[i][1]]);

                // Block_height is relative to the max amount
                min_block_height = 10
                block_height =  ((flows[i][1] / json.max) * 100)
                if (block_height < min_block_height && block_height != 0){
                    block_height = min_block_height    // Minimum block height
                }
                p.b.unshift([x, h += block_height]);
                h += 2;
            }
            // Set dates
            var dt = new Date(json.buckets[j].d * 1000);
            var dtext = dt.getDate() + " " + ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][dt.getMonth()] + " " + dt.getFullYear();
            r.text(x + 25, h + 10, dtext).attr({"font": '9px "Arial"', stroke: "none", fill: "#aaa"});
            x += 100;
        }

        var c = 0;

        // Draw paths
        for (var i in paths) {
            labels[i] = r.set();

            // Set the colours for the blocks.
            min = 100
            max = 240
            colours = 'rgb(' +  getRandomColour(min, max) + ',' + getRandomColour(min, max) + ',' + getRandomColour(min, max) + ')'
            var clr = Raphael.getRGB(colours)
            paths[i].p = r.path().attr({fill: clr, stroke: clr});
            var path = "M".concat(paths[i].f[0][0], ",", paths[i].f[0][1], "L", paths[i].f[0][0] + 50, ",", paths[i].f[0][1]);
            var th = Math.round(paths[i].f[0][1] + (paths[i].b[paths[i].b.length - 1][1] - paths[i].f[0][1]) / 2 + 3);

            // Change `block_label` to change the text on the blocks
            if (th < 20) {block_label = json.labels[i].n + '\n' + paths[i].f[0][2]}
            else {block_label = json.labels[i].n + ' ' + paths[i].f[0][2]}

            labels[i].push(r.text(paths[i].f[0][0] + 25, th, block_label).attr(textattr));

            var X = paths[i].f[0][0] + 50,
                Y = paths[i].f[0][1];
            for (var j = 1, jj = paths[i].f.length; j < jj; j++) {
                path = path.concat("C", X + 20, ",", Y, ",");
                X = paths[i].f[j][0];
                Y = paths[i].f[j][1];
                path = path.concat(X - 20, ",", Y, ",", X, ",", Y, "L", X += 50, ",", Y);
                th = Math.round(Y + (paths[i].b[paths[i].b.length - 1 - j][1] - Y) / 2 + 3);
                if (th - 9 > Y) {
                    // Change `block_label` to change the text on the blocks
                    block_label = json.labels[i].n + '\n' + paths[i].f[j][2]
                    labels[i].push(r.text(X - 25, th, block_label).attr(textattr));
                }
            }
            path = path.concat("L", paths[i].b[0][0] + 50, ",", paths[i].b[0][1], ",", paths[i].b[0][0], ",", paths[i].b[0][1]);
            for (var j = 1, jj = paths[i].b.length; j < jj; j++) {
                path = path.concat("C", paths[i].b[j][0] + 70, ",", paths[i].b[j - 1][1], ",", paths[i].b[j][0] + 70, ",", paths[i].b[j][1], ",", paths[i].b[j][0] + 50, ",", paths[i].b[j][1], "L", paths[i].b[j][0], ",", paths[i].b[j][1]);
            }
            paths[i].p.attr({path: path + "z"});

            // Mouse hover functions
            var current = null;
            (function (i) {
                paths[i].p.mouseover(function () {
                    paths[i].p.toFront();
                    labels[i].toFront();
                    for (path in paths) {
                        paths[path].p.attr("stroke", paths[path].p.attr("fill"))
                    }
                    paths[i].p.attr("stroke", "red").attr("stroke-width", "1");
                });
            })(i);
        }
    }

    function getRandomColour(min, max){
        //returns a random set of colours in RGB between two values
        return (Math.floor((Math.random() * (max - min) + min))).toString()
    }

    if (json.error) {
        alert("Project not found. Try again.");
    } else {
        block();
    }
};