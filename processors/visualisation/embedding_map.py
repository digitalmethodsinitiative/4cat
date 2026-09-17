"""
Project embeddings to two dimensions and render them as an interactive map.
"""
import json

import numpy as np

from backend.lib.processor import BasicProcessor
from common.lib.compatibility import Compatibility
from common.lib.dataset import DataSet
from common.lib.exceptions import DataSetException, ProcessorInterruptedException
from common.lib.user_input import UserInput
from processors.visualisation.media_thumbnails import MediaThumbnails

__author__ = "Sal Hagen"
__credits__ = ["Sal Hagen"]
__maintainer__ = "Sal Hagen"
__email__ = "4cat@oilab.eu"

#: Datasets whose items are media files, and so can be shown as thumbnails
MEDIA_EMBEDDINGS = ("image-embeddings", "video-embeddings")


class EmbeddingMap(BasicProcessor):
    """
    Reduce item embeddings to two dimensions and write a self-contained,
    interactive HTML scatter plot.
    """
    type = "embedding-map"  # job type ID
    category = "Visual"  # category
    title = "Plot embeddings"  # title displayed in UI
    description = ("Reduce the embeddings of each embedding to two dimensions and plot them as an interactive map, so "
                   "items with similar meanings sit near each other. Note that distances may be meaningless (see "
                   "references).")
    extension = "html"  # extension of result file, used internally and in UI

    compatibility = Compatibility(types={"text-embeddings", "video-embeddings", "image-embeddings"})

    references = [
        "[McInnes, Leland, John Healy, and James Melville. 2018. 'UMAP: Uniform Manifold Approximation and Projection "
        "for Dimension Reduction.' arXiv:1802.03426.](https://arxiv.org/abs/1802.03426)",
        "[Understanding UMAP](https://pair-code.github.io/understanding-umap/)",
        "[How to Use t-SNE Effectively](https://distill.pub/2016/misread-tsne/)",
    ]

    @classmethod
    def get_options(cls, parent_dataset=None, config=None) -> dict:
        """
        Get processor options

        :param parent_dataset DataSet:  An object representing the dataset that
            the processor would be or was run on.
        :param config ConfigManager|None config:  Configuration reader (context-aware)
        :return dict:   Options for this processor
        """
        options = {
            "algorithm": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Reduction algorithm",
                "options": {
                    "umap": "UMAP (recommended)",
                    "tsne": "t-SNE",
                    "pca": "PCA",
                },
                "default": "umap",
                "tooltip": "UMAP keeps both local and global structure and is usually the most readable. t-SNE "
                           "separates local clusters sharply but its global layout means little. PCA is fast and "
                           "fully deterministic, but flattens subtle structure.",
            },
            "n_neighbors": {
                "type": UserInput.OPTION_TEXT,
                "help": "UMAP: neighbours",
                "default": 15,
                "min": 2,
                "max": 200,
                "coerce_type": int,
                "tooltip": "How much of the dataset each point is compared against. Low values emphasise small local "
                           "clusters, high values emphasise overall shape.",
                "requires": "algorithm==umap",
            },
            "min_dist": {
                "type": UserInput.OPTION_TEXT,
                "help": "UMAP: minimum distance",
                "default": 0.1,
                "min": 0.0,
                "max": 0.99,
                "coerce_type": float,
                "tooltip": "How tightly points may be packed together. Lower values give denser clumps.",
                "requires": "algorithm==umap",
            },
            "perplexity": {
                "type": UserInput.OPTION_TEXT,
                "help": "t-SNE: perplexity",
                "default": 30,
                "min": 2,
                "max": 100,
                "coerce_type": int,
                "tooltip": "Roughly how many neighbours each point is balanced against. Lowered automatically if the "
                           "dataset is too small.",
                "requires": "algorithm==tsne",
            },
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of items",
                "default": 2000,
                "min": 0,
                "coerce_type": int,
                "tooltip": "Use '0' for all items. Reduction slows down sharply on very large datasets.",
            },
            "max_text_length": {
                "type": UserInput.OPTION_TEXT,
                "help": "Hover text length",
                "default": 250,
                "min": 20,
                "max": 2000,
                "coerce_type": int,
                "tooltip": "Characters of each item's text to show on hover. Lower this if the result file gets too "
                           "large.",
            },
        }

        # allow showing media on the map for media datasets, reusing a sprite
        # sheet extracted earlier rather than decoding the media again here
        sprites = cls.find_sprite_datasets(parent_dataset)
        if sprites:
            options["thumbnails"] = {
                "type": UserInput.OPTION_CHOICE,
                "help": "Thumbnails",
                "options": {"": "No thumbnails, just dots", **sprites},
                "default": "",
                "tooltip": "Draw each item as its thumbnail instead of a dot, using a sprite sheet made earlier by "
                           "the 'Extract thumbnails' processor.",
            }
        elif parent_dataset and parent_dataset.type in MEDIA_EMBEDDINGS:
            options["thumbnails_info"] = {
                "type": UserInput.OPTION_INFO,
                "help": "Run **Extract thumbnails** on the media this dataset came from to draw items as thumbnails "
                        "here instead of dots. It only has to be run once: every map made afterwards can reuse it.",
            }

        return options

    def media_link_base(self) -> str | None:
        """
        URL prefix that serves one file out of the media archive.

        4CAT already serves a single member of a dataset's archive, and enforces
        the dataset's own access rules on every request - so putting these links
        in the map grants nothing: an unauthorised viewer following one still
        gets a 403. Nothing about the media is embedded here, only its address.

        Absolute when the instance knows its own hostname, so a downloaded map
        still resolves; root-relative otherwise, which works inside 4CAT itself.

        :return str|None:  Prefix to append a filename to, or `None` when there
          is no archive to link into.
        """
        archive = self.source_dataset.get_parent()
        if not archive:
            return None

        path = f"/download/{archive.key}/?zip_member="
        server_name = self.config.get("flask.server_name")
        if not server_name:
            return path

        protocol = "https://" if self.config.get("flask.https") else "http://"
        return protocol + server_name.rstrip("/") + path

    @classmethod
    def find_sprite_datasets(cls, parent_dataset) -> dict:
        """
        Find sprite sheets made from the same media as these embeddings.

        Thumbnails belong to the media, not to any one embedding run, so they
        are extracted as a sibling of the embeddings - a child of the archive
        both were derived from. One extraction then serves every map, including
        maps of embeddings made later with a different model.

        :param parent_dataset:  The embeddings dataset the map would run on
        :return dict:  `{dataset key: label}`, empty when there are none.
        """
        if not parent_dataset or parent_dataset.type not in MEDIA_EMBEDDINGS:
            return {}

        archive = parent_dataset.get_parent()
        if not archive:
            return {}

        sprites = {}
        for sibling in archive.get_children():
            if sibling.type != MediaThumbnails.type or not sibling.is_finished():
                continue

            size = sibling.parameters.get("thumbnail_size", "?")
            sprites[sibling.key] = f"{size}px, {sibling.num_rows:,} thumbnails"

        return sprites

    def reduce(self, vectors, point_count):
        """
        Reduce vectors to two dimensions.

        Imports are deliberately local: `ModuleCollector` imports every
        processor at startup, and importing UMAP pulls in numba, whose JIT setup
        makes that noticeably slower for a module most installs never run.

        :param vectors:  2D numpy array of embeddings, one row per item
        :param int point_count:  Number of items
        :return:  2D numpy array of `(x, y)` coordinates
        """
        algorithm = self.parameters.get("algorithm", "umap")

        if algorithm == "pca":
            from sklearn.decomposition import PCA
            return PCA(n_components=2, random_state=42).fit_transform(vectors)

        if algorithm == "tsne":
            from sklearn.manifold import TSNE
            # perplexity must stay below the item count or sklearn refuses to run
            perplexity = min(self.parameters.get("perplexity", 30), max(2.0, (point_count - 1) / 3))
            self.dataset.log(f"Running t-SNE with perplexity {perplexity}")
            return TSNE(n_components=2, perplexity=perplexity, metric="cosine", init="pca",
                        random_state=42).fit_transform(vectors)

        import umap
        # n_neighbors cannot exceed the number of other points available
        n_neighbors = min(self.parameters.get("n_neighbors", 15), point_count - 1)
        min_dist = self.parameters.get("min_dist", 0.1)
        self.dataset.log(f"Running UMAP with n_neighbors={n_neighbors}, min_dist={min_dist}")

        # cosine is the metric embeddings are meant to be compared under, and a
        # fixed random_state keeps the map reproducible - 4CAT results should be
        # retraceable, which a different layout on every run would undermine
        return umap.UMAP(n_components=2, n_neighbors=n_neighbors, min_dist=min_dist, metric="cosine",
                         random_state=42).fit_transform(vectors)

    def process(self):
        """
        Reduce the embeddings and write the interactive map.
        """
        limit = self.parameters.get("amount", 2000)
        max_processed = min(limit, self.source_dataset.num_rows) if limit else self.source_dataset.num_rows
        max_text_length = self.parameters.get("max_text_length", 250)

        vectors = []
        labels = []
        filenames = []
        dimensions = None

        self.dataset.update_status("Reading embeddings")
        for item in self.source_dataset.iterate_items(self):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while reading embeddings")

            if len(vectors) >= max_processed:
                break

            vector = item.get("embedding")
            # map_item flattens the vector to a space-separated string; the raw
            # NDJSON keeps it as a list. Accept either.
            if isinstance(vector, str):
                vector = [float(value) for value in vector.split() if value]

            if not vector:
                continue

            if dimensions is None:
                dimensions = len(vector)
            elif len(vector) != dimensions:
                # a ragged matrix cannot be reduced; this means the dataset mixes
                # models, which should not happen but is worth saying out loud
                self.dataset.finish_with_error("The parent dataset contains embeddings of different sizes, so they "
                                               "cannot be mapped together.")
                return

            vectors.append(vector)
            text = str(item.get("text", "") or "")
            labels.append(text[:max_text_length] + ("…" if len(text) > max_text_length else ""))
            filenames.append(str(item.get("filename", "") or ""))

        point_count = len(vectors)
        if point_count < 3:
            self.dataset.finish_with_error(f"Not enough embeddings to build a map (found {point_count}, need at "
                                           f"least 3).")
            return

        self.dataset.update_status(f"Reducing {point_count:,} embeddings of {dimensions} dimensions to 2D; this may "
                                   f"take a while")
        coordinates = self.reduce(np.asarray(vectors, dtype=np.float32), point_count)

        atlas = self.load_sprite(filenames) if any(filenames) else None

        self.dataset.update_status("Rendering map")
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            outfile.write(self.get_html(coordinates, labels, atlas))

        self.dataset.update_status(f"Mapped {point_count:,} items", is_final=True)
        self.dataset.finish(point_count)

    def load_sprite(self, filenames: list) -> dict | None:
        """
        Read the chosen sprite sheet and line its tiles up with the points.

        The sheet keys tiles by filename rather than position, so the map is
        free to cap, filter or reorder its own items without the tiles going out
        of step; items the sheet does not cover simply fall back to a dot.

        :param list filenames:  Media filename per point, in point order
        :return dict|None:  `{uri, tile, cols, tiles}` with `tiles[i]` the tile
          index for point `i` (-1 for none), or `None` if unusable.
        """
        key = self.parameters.get("thumbnails")
        if not key:
            return None

        try:
            sprite_dataset = DataSet(key=key, db=self.db, modules=self.modules)
        except DataSetException:
            self.dataset.log("Not drawing thumbnails: the sprite sheet dataset no longer exists.")
            return None

        sprite = MediaThumbnails.read_sprite(sprite_dataset)
        if not sprite:
            self.dataset.log("Not drawing thumbnails: the sprite sheet could not be read.")
            return None

        lookup = sprite["tiles"]
        tiles = [lookup.get(filename, -1) for filename in filenames]
        matched = sum(1 for tile in tiles if tile > -1)
        if not matched:
            self.dataset.log("Not drawing thumbnails: the sprite sheet has no tiles for these items.")
            return None

        self.dataset.log(f"Using {matched:,} of {len(tiles):,} thumbnails from sprite sheet {key}")

        return {
            "uri": sprite["uri"],
            "tile": sprite["tile"],
            "cols": sprite["cols"],
            "tiles": tiles,
            # only link files the sheet actually covers, so a click never opens
            # something the map is not showing
            "files": [name if tile > -1 else "" for name, tile in zip(filenames, tiles)],
            "base": self.media_link_base() or "",
        }

    def get_html(self, coordinates, labels, atlas: dict | None = None) -> str:
        """
        Build the self-contained HTML page.

        The result is rendered into a 4CAT page with `{{ html|safe }}` as well as
        opened directly when downloaded, so it carries no `<html>`/`<body>`
        wrapper, scopes its CSS to one container, and keeps its JavaScript in an
        IIFE rather than touching globals.

        It does carry a charset declaration: 4CAT's own page declares UTF-8, but
        a downloaded file has nothing to inherit from, and item text is routinely
        non-ASCII. Without it the browser guesses, and guesses latin-1.

        :param coordinates:  2D numpy array of `(x, y)` coordinates
        :param list labels:  Hover text per point, in the same order
        :param dict atlas:  Sprite sheet from `build_atlas()`, or `None` to draw
          plain dots
        :return str:  HTML
        """
        # normalise to 0-1 so the client only deals with its own viewport
        mins = coordinates.min(axis=0)
        spans = np.where(coordinates.max(axis=0) - mins == 0, 1, coordinates.max(axis=0) - mins)
        normalised = (coordinates - mins) / spans

        points = [[round(float(x), 5), round(float(y), 5)] for x, y in normalised]

        # Item text is untrusted - it comes from whatever platform the dataset
        # was collected from - and this page is injected into 4CAT's own DOM
        # unescaped. Escaping the angle brackets and ampersand means no item can
        # close the script tag or inject markup, whatever it contains.
        data = {"points": points, "labels": labels}
        if atlas:
            # base64 is alphanumeric plus + / =, so the escaping below leaves it
            # untouched
            data.update({"atlas": atlas["uri"], "tile": atlas["tile"],
                         "cols": atlas["cols"], "tiles": atlas["tiles"],
                         "files": atlas["files"], "base": atlas["base"]})

        payload = json.dumps(data, ensure_ascii=False)
        payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

        container = f"embedding-map-{self.dataset.key}"
        subtitle = f"{len(points):,} items &middot; {self.parameters.get('algorithm', 'umap').upper()}"
        if atlas:
            drawn = sum(1 for tile in atlas["tiles"] if tile > -1)
            subtitle += f" &middot; {drawn:,} thumbnails"

        interaction = "scroll to zoom, drag to pan"
        if atlas and atlas.get("base"):
            interaction += ", click to open the media"

        return HTML_TEMPLATE % {"container": container, "payload": payload, "subtitle": subtitle,
                                "interaction": interaction}


HTML_TEMPLATE = """<meta charset="utf-8">
<div id="%(container)s" class="embedding-map">
<style>
#%(container)s { position: relative; width: 100%%; height: 80vh; min-height: 420px; margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #fbfbfc; border: 1px solid #dcdce0; box-sizing: border-box; }
#%(container)s canvas { display: block; width: 100%%; height: 100%%; cursor: grab; }
#%(container)s canvas.dragging { cursor: grabbing; }
#%(container)s canvas.clickable { cursor: pointer; }
#%(container)s .em-bar { position: absolute; top: 0; left: 0; right: 0; display: flex; justify-content: space-between; align-items: center; padding: 8px 12px; font-size: 12px; color: #55555c; background: linear-gradient(#fbfbfcef, #fbfbfc00); pointer-events: none; }
#%(container)s .em-bar button { pointer-events: auto; font: inherit; font-size: 11px; padding: 3px 9px; border: 1px solid #cacad0; border-radius: 3px; background: #fff; color: #33333a; cursor: pointer; }
#%(container)s .em-bar button:hover { background: #f0f0f3; }
#%(container)s .em-tip { position: absolute; max-width: 320px; padding: 8px 10px; font-size: 12px; line-height: 1.45; color: #1c1c20; background: #fff; border: 1px solid #cacad0; border-radius: 4px; box-shadow: 0 2px 10px #00000026; pointer-events: none; opacity: 0; transition: opacity .1s; white-space: pre-wrap; overflow-wrap: anywhere; z-index: 2; }
#%(container)s .em-tip.visible { opacity: 1; }
</style>
<div class="em-bar"><span>%(subtitle)s &middot; %(interaction)s</span><button type="button" data-reset>Reset view</button></div>
<canvas></canvas>
<div class="em-tip"></div>
</div>
<script>
(function () {
    var root = document.getElementById("%(container)s");
    if (!root || root.dataset.ready) return;
    root.dataset.ready = "1";

    var data = %(payload)s;
    var points = data.points, labels = data.labels;
    var tiles = data.tiles || null, tileSize = data.tile || 0, atlasCols = data.cols || 1;
    var files = data.files || null, linkBase = data.base || "";

    // the address of the media behind a point, or "" when there is none
    function linkFor(i) {
        if (!files || !linkBase || i < 0 || !files[i]) return "";
        return linkBase + encodeURIComponent(files[i]);
    }
    var atlas = null;
    if (data.atlas) {
        atlas = new Image();
        // one decode for every thumbnail; redraw once it is ready
        atlas.onload = function () { draw(); };
        atlas.src = data.atlas;
    }
    var canvas = root.querySelector("canvas"), ctx = canvas.getContext("2d");
    var tip = root.querySelector(".em-tip");
    var RADIUS = 3.2, PAD = 36;
    var view = {scale: 1, x: 0, y: 0}, width = 0, height = 0, hovered = -1;

    function resize() {
        var dpr = window.devicePixelRatio || 1, box = canvas.getBoundingClientRect();
        width = box.width; height = box.height;
        canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        draw();
    }

    // normalised coordinates -> canvas pixels, with the current pan/zoom applied
    function project(p) {
        return [PAD + p[0] * (width - PAD * 2) * view.scale + view.x,
                PAD + (1 - p[1]) * (height - PAD * 2) * view.scale + view.y];
    }

    // thumbnails grow with zoom up to their stored size; beyond that they would
    // only get blurry, and below ~14px they are unreadable anyway
    function thumbScale() {
        return Math.max(14, Math.min(tileSize, 16 * view.scale));
    }

    // blit one tile out of the sprite sheet, or fall back to a dot for an item
    // whose thumbnail could not be made
    function drawTile(i, xy, drawn) {
        var tile = tiles[i];
        if (tile < 0 || !atlas || !atlas.complete) {
            ctx.beginPath(); ctx.arc(xy[0], xy[1], RADIUS, 0, 6.2832); ctx.fill();
            return;
        }
        var sx = (tile %% atlasCols) * tileSize, sy = Math.floor(tile / atlasCols) * tileSize;
        ctx.drawImage(atlas, sx, sy, tileSize, tileSize,
                      xy[0] - drawn / 2, xy[1] - drawn / 2, drawn, drawn);
    }

    function draw() {
        ctx.clearRect(0, 0, width, height);
        ctx.fillStyle = "rgba(40, 92, 168, 0.55)";
        var drawn = tiles ? thumbScale() : 0;
        var margin = tiles ? drawn : 10;

        for (var i = 0; i < points.length; i++) {
            if (i === hovered) continue;
            var xy = project(points[i]);
            if (xy[0] < -margin || xy[0] > width + margin || xy[1] < -margin || xy[1] > height + margin) continue;
            if (tiles) drawTile(i, xy, drawn);
            else { ctx.beginPath(); ctx.arc(xy[0], xy[1], RADIUS, 0, 6.2832); ctx.fill(); }
        }

        if (hovered > -1) {
            var h = project(points[hovered]);
            if (tiles) {
                // draw the hovered one last and larger, with an outline, so it
                // is legible even in a dense patch
                var big = Math.min(tileSize * 1.5, drawn * 1.8);
                drawTile(hovered, h, big);
                ctx.strokeStyle = "#d2451e"; ctx.lineWidth = 2;
                ctx.strokeRect(h[0] - big / 2, h[1] - big / 2, big, big);
            } else {
                ctx.fillStyle = "#d2451e";
                ctx.beginPath(); ctx.arc(h[0], h[1], RADIUS + 2.5, 0, 6.2832); ctx.fill();
                ctx.strokeStyle = "#fff"; ctx.lineWidth = 1.5; ctx.stroke();
            }
        }
    }

    function nearest(mx, my) {
        // linear scan: simpler than a spatial index and fast enough at the item
        // counts this processor caps at
        var best = -1, bestDist = 144;
        for (var i = 0; i < points.length; i++) {
            var xy = project(points[i]);
            var d = (xy[0] - mx) * (xy[0] - mx) + (xy[1] - my) * (xy[1] - my);
            if (d < bestDist) { bestDist = d; best = i; }
        }
        return best;
    }

    canvas.addEventListener("mousemove", function (e) {
        var box = canvas.getBoundingClientRect(), mx = e.clientX - box.left, my = e.clientY - box.top;
        if (drag.active) {
            if (Math.abs(mx - drag.startX) > 3 || Math.abs(my - drag.startY) > 3) drag.moved = true;
            view.x = drag.viewX + (mx - drag.startX); view.y = drag.viewY + (my - drag.startY);
            draw(); return;
        }
        var found = nearest(mx, my);
        canvas.classList.toggle("clickable", !!linkFor(found));
        if (found !== hovered) {
            hovered = found;
            if (found > -1) {
                tip.textContent = labels[found] || "(no text)";
                tip.classList.add("visible");
            } else tip.classList.remove("visible");
            draw();
        }
        if (hovered > -1) {
            // keep the tooltip inside the container instead of overflowing it
            var tw = tip.offsetWidth, th = tip.offsetHeight;
            tip.style.left = Math.min(Math.max(8, mx + 14), Math.max(8, width - tw - 8)) + "px";
            tip.style.top = (my - th - 12 < 8 ? my + 18 : my - th - 12) + "px";
        }
    });

    canvas.addEventListener("mouseleave", function () {
        hovered = -1; tip.classList.remove("visible"); draw();
    });

    canvas.addEventListener("wheel", function (e) {
        e.preventDefault();
        var box = canvas.getBoundingClientRect(), mx = e.clientX - box.left, my = e.clientY - box.top;
        var factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
        var next = Math.min(Math.max(view.scale * factor, 0.5), 60);
        factor = next / view.scale;
        // zoom toward the cursor, so the point under it stays put
        view.x = mx - (mx - view.x) * factor;
        view.y = my - (my - view.y) * factor;
        view.scale = next;
        draw();
    }, {passive: false});

    var drag = {active: false, moved: false, startX: 0, startY: 0, viewX: 0, viewY: 0};
    canvas.addEventListener("mousedown", function (e) {
        var box = canvas.getBoundingClientRect();
        drag = {active: true, moved: false, startX: e.clientX - box.left, startY: e.clientY - box.top,
                viewX: view.x, viewY: view.y};
        canvas.classList.add("dragging");
        tip.classList.remove("visible"); hovered = -1;
    });
    window.addEventListener("mouseup", function () {
        drag.active = false; canvas.classList.remove("dragging");
    });

    canvas.addEventListener("click", function (e) {
        // panning ends in a mouseup too; only a press that stayed put is a click
        if (drag.moved) return;
        var box = canvas.getBoundingClientRect();
        var url = linkFor(nearest(e.clientX - box.left, e.clientY - box.top));
        // noopener: the map is rendered inside 4CAT, and the opened page has no
        // business reaching back into it
        if (url) window.open(url, "_blank", "noopener");
    });

    root.querySelector("[data-reset]").addEventListener("click", function () {
        // drop the hover too: the tooltip describes a point that is about to
        // move, so leaving it up would label the wrong place
        view = {scale: 1, x: 0, y: 0};
        hovered = -1; tip.classList.remove("visible");
        draw();
    });

    window.addEventListener("resize", resize);
    resize();
})();
</script>
"""
