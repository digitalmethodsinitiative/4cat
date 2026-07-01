"""
Generate word tree from dataset
"""
import string
import emoji
import jieba
import re

from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput, convert_to_int, get_4cat_canvas
from common.lib.exceptions import QueryParametersException
from common.lib.compatibility import Compatibility
from common.lib.outputs import Render

from nltk.tokenize import word_tokenize, TweetTokenizer

from svgwrite.container import SVG, Script, Style
from svgwrite.shapes import Rect
from svgwrite.path import Path
from svgwrite.text import Text

from math import ceil, sin, pi
from anytree import Node, PreOrderIter

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"



class TreeNode(Node):
    """
    An anytree Node, but with some extra plumbing to give nodes directionality
    """

    def __init__(self, *args, **kwargs):
        """
        Constructor

        Initialises the `bbox` property.

        :param args:
        :param kwargs:
        """
        super().__init__(*args, **kwargs)
        self.bbox = {}
        self.weight = 0

    def get_child(self, name: str, direction: int) -> bool | Node:
        """
        Get children with a specific direction

        :param str name:  Node name
        :param int direction:  Direction, one of the `SIDE_*` constants
        :return:  The first matching node, or `False`
        """
        for node in self.children:
            if node.name == name and node.has_direction(direction, inclusive=True):
                return node

        return False

    def has_direction(self, direction: int, inclusive: bool = False) -> bool:
        """
        Test if node has the required direction

        :param direction:  Direction, one of the `SIDE_*` constants
        :param bool inclusive:  If `True`, also return `True` if the node has
          no direction (i.e. if it is the root node)
        :return:  Whether the node has the required direction
        """
        if not hasattr(self, "direction"):
            return inclusive
        else:
            return self.direction == direction

    def get_parents(self):
        return self.path if hasattr(self, "parents") else []

    @property
    def id(self) -> str:
        """
        Get node ID

        This is equivalent to the node path

        :return str:  Node ID
        """
        return "/".join([re.sub(r"[^a-zA-Z0-9-]*", "", n.name) for n in self.iter_path_reverse()])


class Fragment:
    """
    Simple class for text fragments

    Fragments have two components, a value and a direction (does that make them vectors?)
    """

    def __init__(self, value: list, direction: int):
        """
        Constructor

        :param list value:  The value, as a list of tokens
        :param int direction:  Direction, one of the `SIDE_*` constants
        """
        self.value = value
        self.direction = direction

class WildcardMatcher:
    """
    Plumbing for matching wildcard (* and ?) strings
    """
    # can't really think of a better way than this
    dictionary = {
        "*": "OOOOOXXOOOOOXXOOOOOXXOOOOOASTERISKOOOOOXXOOOOOXXOOOOOXXOOOOO",
        "?": "OOOOOXXOOOOOXXOOOOOXXOOOOOQMARKOOOOOXXOOOOOXXOOOOOXXOOOOO",
    }

    def __init__(self):
        """
        Initialise cache
        """
        self._cache = {}

    def obfuscate(self, q: str) -> str:
        """
        Obfuscate a wildcard string

        Useful to avoid considering the wildcard syntax as a token boundary
        while tokenising.

        :param str q:
        :return str:
        """
        for s, r in WildcardMatcher.dictionary.items():
            q = q.replace(s, r)
        return q

    def deobfuscate(self, q: str) -> str:
        """
        Deobfuscate a wildcard string

        :param str q:
        :return str:
        """
        for s, r in WildcardMatcher.dictionary.items():
            q = q.replace(r, s)
        return q

    def compile(self, q: str) -> re.Pattern|None:
        """
        Compile a regular expression for matching

        Escapes all regex syntax currently in the match string. Regular
        expressions are cached. If the query does not contain wildcard
        characters, return `None` (signalling that plain string matching can be
        used)

        :param str q:  Query string (may contain `*` and `?` wildcards)
        :return re.Pattern|None:  Regular expression object, or `None`
        """
        if q not in self._cache:
            worked_q = self.obfuscate(q)
            worked_q = re.escape(worked_q)
            worked_q = self.deobfuscate(worked_q)
            if re.findall(r"[*?]", worked_q):
                worked_q = worked_q.replace("*", ".*?").replace("?", ".")
                self._cache[q] = re.compile(worked_q)
            else:
                self._cache[q] = None

        return self._cache[q]

    def fullmatch(self, needle: str, haystack:str) -> bool:
        """
        Match a needle against a haystack

        :param str needle:  Query string (may contain `*` and `?` wildcards)
        :param str haystack:  Haystack to search
        :return bool:  Do the strings match?
        """
        pattern = self.compile(needle)
        if pattern is None:
            return needle == haystack
        else:
            return bool(pattern.fullmatch(haystack))


class MakeWordtree(BasicProcessor):
    """
    Generate word tree from dataset

    Inspired by https://www.jasondavies.com/wordtree/.
    """

    type = "word-trees"  # job type ID
    category = "Visual"  # category
    title = "Word tree"  # title displayed in UI
    description = "Generates a word tree for a given query, a \"graphical version of the traditional 'keyword-in-context' method\" (Wattenberg & Viégas, 2008)."  # description displayed in UI
    extension = "svg"  # extension of result file, used internally and in UI
    # a rendered image, no column table
    output = Render()
    icon = "tree"

    # any csv or ndjson dataset
    compatibility = Compatibility(extensions={"csv", "ndjson"})

    references = [
        "Wattenberg, M., & Viégas, F. B. (2008). [The Word Tree, an Interactive Visual Concordance](https://doi.org/10.1109/TVCG.2008.172). IEEE Transactions on Visualization and Computer Graphics, 14(6), 1221–1228.",
        "[NLTK tokenizer documentation](https://www.nltk.org/api/nltk.tokenize.html)",
        "[Different types of tokenizers in NLTK](https://chendianblog.wordpress.com/2016/11/25/different-types-of-tokenizers-in-nltk/)",
    ]

    # can be changed
    FONT_SIZE = 14  # in px
    FONT_FACTOR_MAX = 3  # how big can the font get?

    # will be adjusted based on tokeniser used
    SPACE = ""

    # tbd on load
    align = "top"

    # convert between relative and absolute units
    REM_TO_CH = 0.601875
    REM_CONV = FONT_SIZE
    CH_CONV = FONT_SIZE * REM_TO_CH

    # gaps between nodes vertically and horizontally
    gap_x = 4
    gap_y = 1

    # to be used later to determine dimensions of graph
    x_min = 0
    x_max = 0

    # for the user!
    progress = 0

    # constants
    SIDE_LEFT = -1
    SIDE_RIGHT = 1

    # colour palette via https://medialab.github.io/iwanthue/
    palette = ["#ff6c55", "#0948b9", "#acad13", "#7f7cf7", "#72b636", "#51006f", "#b9e272", "#a23fb0", "#00bf82",
               "#a90580", "#01bd9e", "#c10f78", "#8fe6b3", "#d2264a", "#739dff", "#fdaa3a", "#004ca2", "#f8ce80"]

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options
        """
        options = {
            "columns": {
                "type": UserInput.OPTION_TEXT,
                "help": "Column(s) with text",
                "tooltip": "Texts from each selected column will be taken into account for the word tree."
            },
            "query": {
                "type": UserInput.OPTION_TEXT,
                "default": "",
                "help": "Word tree root query",
                "tooltip": "Enter a text here to serve as the root of the word tree. The context of this query will be "
                           "visualised as a tree graph. You can use wildcards: 'politic*' will match 'politician' and "
                           "'politics' for example, though this is more computationally intensive and will make the "
                           "processor much slower.",
            },
            "limit": {
                "type": UserInput.OPTION_TEXT,
                "default": 3,
                "min": 1,
                "max": 25,
                "help": "Max branches/level",
                "tooltip": "Limit the amount of branches per level, sorted by most-occuring fragments. Range 1-25.",
            },
            "window": {
                "type": UserInput.OPTION_TEXT,
                "min": 1,
                "max": 25,
                "default": 10,
                "help": "Window size",
                "tooltip": "Up to this many words before and/or after the queried phrase will be visualised",
            },
            "sides": {
                "type": UserInput.OPTION_CHOICE,
                "default": "both",
                "options": {
                    "only-left": "Before query",
                    "only-right": "After query",
                    "both": "Before and after query",
                },
                "help": "Query context to visualise",
            },
            "align": {
                "type": UserInput.OPTION_CHOICE,
                "default": "middle",
                "options": {
                    "middle": "Vertically centered",
                    "top": "Top",
                    "bottom": "Bottom",
                },
                "help": "Visual alignment",
            },
            "tokeniser_type": {
                "type": UserInput.OPTION_CHOICE,
                "default": "nltk-tweet",
                "options": {
                    "nltk-tweet": "nltk TweetTokenizer (optimized for social media)",
                    "nltk-word": "nltk word_tokenize",
                    "jieba-cut": "jieba (for Chinese text; accurate mode, recommended)",
                    "jieba-cut-all": "jieba (for Chinese text; full mode)",
                    "jieba-search": "jieba (for Chinese text; search engine suggestion style)",
                },
                "help": "Tokeniser",
                "tooltip": "What heuristic to use to split up the text into separate words.",
            },
            "strip-urls": {
                "type": UserInput.OPTION_TOGGLE,
                "default": True,
                "help": "Remove URLs",
            },
            "strip-symbols": {
                "type": UserInput.OPTION_TOGGLE,
                "default": True,
                "help": "Remove punctuation",
                "tooltip": "Remove punctuation. Adjust your query accordingly (e.g. after removing punctuation, the "
                           "query 'a.i.' will match nothing).",
            },
            "lower-case": {
                "type": UserInput.OPTION_TOGGLE,
                "default": True,
                "help": "Make all text lower case",
                "tooltip": "If not checked, e.g. 'The' and 'the' will be considered separate branches of the word tree"
            }
        }

        # Get the columns for the select columns option
        if parent_dataset and parent_dataset.get_columns():
            columns = parent_dataset.get_columns()
            options["columns"]["type"] = UserInput.OPTION_MULTI
            options["columns"]["inline"] = True
            options["columns"]["options"] = {v: v for v in columns}
            default_options = [
                default for default in ["body", "text", "subject"] if default in columns
            ]
            if default_options:
                options["columns"]["default"] = default_options.pop(0)

        return options

    def process(self):
        """
        This takes a 4CAT results file as input, and outputs a plain text file
        containing all post bodies as one continuous string, sanitized.
        """
        self.align = self.parameters.get("align")
        sides = self.parameters.get("sides")

        # nice label
        self.dataset.update_label(f"Word tree: '{self.parameters.get('query')}'")

        # build our tree of text fragments
        root, self.max_weight = self.build_tree(self.parameters.get("query"))

        if not root or not root.children:
            return self.dataset.finish_with_error(f"Query '{self.parameters.get('query')}' not found in dataset")

        # while we're at it, we also calculate the (approximate) dimensions of
        # each branch, which we will need for rendering it later
        width_left, height_left = self.get_bbox(root, self.SIDE_LEFT)
        width_right, height_right = self.get_bbox(root, self.SIDE_RIGHT)
        height = max(height_left, height_right)

        # depending on which side of the tree is higher, we need to adjust the
        # height of the other side; and we need to decide which side of the
        # tree gets to draw the root node, since we can't have both sides draw
        # it
        origin_left_y, origin_right_y = 0, 0
        root_side = "right" if sides == "only-right" else "left"
        if sides == "both":
            root_side = "right" if height_right > height_left else "left"

        if self.align == "middle":
            if height_left > height_right:
                origin_right_y = int((height / 2) - (height_right / 2))
            else:
                origin_left_y = int((height / 2) - (height_left / 2))
        elif self.align == "bottom":
            origin_right_y = height - height_right
            origin_left_y = height - height_left

        # the nodes on the left side of the graph now have the wrong word order,
        # because we reversed them earlier to generate the correct tree
        # hierarchy - now reverse the node labels so they are proper language
        # again
        self.invert_node_labels(root)

        self.dataset.update_status(f"Rendering tree to SVG file (root side: {root_side})")
        wrapper = SVG(overflow="visible", debug=False, id="tree")
        offset_x = 0

        if sides != "only-right":
            self.dataset.update_status("Adding left side of tree to SVG file")
            wrapper, _ = self.render(
                wrapper,
                root,
                y=origin_left_y,
                height=height,
                side=self.SIDE_LEFT,
                draw_root=root_side == "left"
            )

            # shift the rest of the tree to the right of this half
            offset_x += width_left - self.get_bbox(root, self.SIDE_LEFT, False)[0]

        if sides != "only-left":
            self.dataset.update_status("Adding right side of tree to SVG file")
            wrapper, _ = self.render(
                wrapper,
                root,
                x=offset_x,
                y=origin_right_y,
                height=height,
                side=self.SIDE_RIGHT,
                draw_root=root_side == "right"
            )

        # things may have been rendered outside the canvas, so we readjust the
        # canvas size to include everything that's been drawn
        # also add a margin to give the graph some room to breathe
        margin = 2
        x_shift = 0 if self.x_min >= 0 else self.x_min * -1
        y_shift = 0
        x_shift += margin
        y_shift += margin

        wrapper.update({"x": f"{x_shift}ch", "y": f"{y_shift}rem"})
        canvas = get_4cat_canvas(
            self.dataset.get_results_path(),
            (ceil(self.x_max - self.x_min) + (2 * margin)) * self.CH_CONV,
            (height + (2 * margin)) * self.REM_CONV,
            None,
            fontsize_normal=self.FONT_SIZE,
            fontsize_large=self.FONT_SIZE * 1.5,
            fontsize_small=self.FONT_SIZE * 0.8
        )

        canvas.add(Script(content=self.get_svg_script()))
        canvas.defs.add(Style(self.get_css()))
        canvas.add(wrapper)
        canvas.add(Rect((25, canvas["height"] - 25 - 25), (25, 25), fill=self.palette[0], style="cursor:pointer",
                        id="toggle-colour", stroke="#000"))
        canvas.save(pretty=True)

        return self.dataset.finish(len(list(PreOrderIter(root))))

    @staticmethod
    def validate_query(query, request, config):
        """
        Validate input

        Checks if everything needed is filled in.

        :param query:
        :param request:
        :param config:
        :return:
        """
        if not query.get("query", "").strip():
            raise QueryParametersException("Query cannot be empty.")

        return query

    def build_tree(self, query: str) -> tuple[TreeNode, int]:
        """
        Build a tree of text fragments to then visualise

        :param str query:  Query to build tree around
        :return tuple:  A tuple with a reference to the root of the tree and
          the max node weight encountered
        """

        sides = self.parameters.get("sides")
        window = max(1, convert_to_int(self.parameters.get("window"), 5) + 1)
        lowercase = self.parameters.get("lower-case")

        # determine what tokenisation strategy to use
        tokeniser_args = {}
        if self.parameters.get("tokeniser_type") == "jieba-cut":
            tokeniser = jieba.cut
            tokeniser_args = {"cut_all": False}
        elif self.parameters.get("tokeniser_type") == "jieba-cut-all":
            tokeniser = jieba.cut
            tokeniser_args = {"cut_all": True}
        elif self.parameters.get("tokeniser_type") == "jieba-search":
            tokeniser = jieba.cut_for_search
        elif self.parameters.get("tokeniser_type") == "nltk-word":
            self.SPACE = " "
            tokeniser = word_tokenize
        else:
            self.SPACE = " "
            tokeniser = TweetTokenizer(preserve_case=False).tokenize

        # tokenise query
        matcher = WildcardMatcher()
        if lowercase:
            query = query.lower()

        tokenised_query = tokeniser(matcher.obfuscate(query), **tokeniser_args)
        tokenised_query = [matcher.deobfuscate(q) for q in tokenised_query]
        if type(tokenised_query) is not list:
            tokenised_query = list(tokenised_query)

        query_token_length = len(tokenised_query)

        def list_in_list(needle: list, haystack: list):
            if len(needle) > len(haystack):
                return

            for i in range(len(haystack) - len(needle) + 1):
                if all(matcher.fullmatch(needle[j], haystack[i + j]) for j in range(len(needle))):
                    yield i

        # find matching posts
        processed = 0
        fragments = []
        columns = self.parameters.get("columns", [])
        if type(columns) is not list:
            columns = [columns]

        link_regex = re.compile(r"https?://\S+")
        strip_urls = self.parameters.get("strip-urls")
        strip_symbols = self.parameters.get("strip-symbols")
        punctuation = string.punctuation + "‘’“”‚„′″…–—«»"  # string.punctuation isn't quite complete
        punkt_replace = re.compile(r"[" + re.escape(punctuation) + "]")

        for post in self.source_dataset.iterate_items():
            processed += 1
            if processed % 500 == 0:
                self.dataset.update_status(
                    f"Finding query in {processed:,} of {self.source_dataset.num_rows:,} items ({len(fragments):,} matches)")
                self.dataset.update_progress((processed / self.source_dataset.num_rows) * 0.95)

            for column in columns:
                document = post.get(column)

                try:
                    document = str(document)
                except TypeError:
                    continue

                if strip_urls:
                    document = link_regex.sub("", document)

                if strip_symbols:
                    document = punkt_replace.sub("", document)

                if not document:
                    continue

                if lowercase:
                    document = document.lower()

                document = tokeniser(document, **tokeniser_args)
                if type(document) is not list:
                    # Convert generator to list
                    document = list(document)

                for position in list_in_list(tokenised_query, document):
                    if sides != "only-left":
                        fragment = document[position + query_token_length:position + window + query_token_length - 1]
                        fragments.append(Fragment(fragment, self.SIDE_RIGHT))
                    if sides != "only-right":
                        # reverse order - we un-reverse with invert_node_labels() later
                        fragment = document[max(0, position - window + 1):position][::-1]
                        fragments.append(Fragment(fragment, self.SIDE_LEFT))

        # here is our tree's root node (token)
        root = TreeNode(tokenised_query[0])
        query_start = root
        root.weight = len(fragments)  # occurs in every fragment, after all
        # if we have a longer query, add the rest as nodes already
        # these will be consolidated into a single node in the next steps
        for other_token in tokenised_query[1:]:
            query_start = TreeNode(other_token, parent=query_start)

        self.dataset.update_status("Cleaning up and sorting text fragments")
        # build the tree: each node a token, with all single tokens following it as a
        # child node, recursively. this gets us, for example:
        #   never
        #   `- gonna
        #      `- give
        #         `- you
        #            `- up
        #      `- let
        #         `- you
        #            `- down
        for fragment in fragments:
            current_node = root if fragment.direction == self.SIDE_LEFT else query_start

            for token in fragment.value:
                child_node = current_node.get_child(token, fragment.direction)
                if not child_node:
                    child_node = TreeNode(token, parent=current_node, direction=fragment.direction)

                child_node.weight += 1
                current_node = child_node

        # consolidate strings of single-child nodes
        # this merges non-branching lists of tokens, so we get:
        #   never gonna
        #   `- give you up
        #   `- let you down
        def consolidate(node, side=None):
            directional_children = [n for n in node.children if not side or n.has_direction(side, inclusive=True)]

            while len(directional_children) == 1:
                consolidated_node = directional_children[0]
                joiner = self.SPACE if consolidated_node.name not in string.punctuation else ""
                node.name = joiner.join([node.name, consolidated_node.name])
                node.weight = consolidated_node.weight
                for grandchild in consolidated_node.children:
                    grandchild.parent = node

                node.children = [child for child in node.children if child != consolidated_node]
                directional_children = [n for n in node.children if
                                        not side or n.has_direction(side, inclusive=True)]

            for child in node.children:
                consolidate(child, side=side)

        consolidate(root)

        # if the query is multi-token, it has not been consolidated if the
        # tree goes in two directions (since all nodes will have branches in
        # two directions), so do so as a special case
        consolidate(root, self.SIDE_RIGHT)

        # now get the *second* largest weight as the baseline
        # since the root node will always have more, and usually *far* more
        # occurrences than anything else
        weights = sorted([node.weight for node in PreOrderIter(root)])
        max_weight = weights[-2] if len(weights) > 1 else weights[-1]

        # prune branches, sorting by weight and keeping only the top weightiest
        # we limit this per side - i.e. for both sides, keep track of top x
        # nodes separately. the root node is considered part of the right side
        # for this purpose
        self.dataset.update_status("Sorting and pruning tree branches")
        def arrange(node, limit):
            children_left = sorted(
                [c for c in node.children if c.has_direction(self.SIDE_LEFT)],
                key=lambda c: c.weight, reverse=True)[:limit]
            children_right = sorted(
                [c for c in node.children if c.has_direction(self.SIDE_RIGHT, inclusive=True)],
                key=lambda c: c.weight, reverse=True)[:limit]
            node.children = [*children_right, *children_left]
            for child in node.children:
                arrange(child, limit)

        arrange(root, convert_to_int(self.parameters.get("limit"), 100))

        return root, max_weight

    def render(
            self,
            canvas: SVG,
            node: TreeNode,
            x: float = 0,
            y: float = 0,
            height: float = 0,
            origin: tuple | bool = None,
            side: int = 1,
            draw_root: bool = True,
            depth: int = 0
    ) -> tuple[SVG, float]:
        """
        Render node to canvas

        Because we're using a monospace font to determine position and size,
        we can use rem (i.e. font size) for height and ch (i.e. width of the
        '0' charachter, but actually all characters because minispace) for
        vertical positioning.

        :param SVG canvas:  Canvas, as an SVG document
        :param TreeNode node:  Node to render
        :param float x:  Top left coordinate of node container
        :param float y:  Top left coordinate of node container
        :param float height: Full container height
        :param tuple origin: Coordinates to connect bezier spline to
        :param int side:  Is this node on the left or right side of the graph?
        :param bool draw_root:  Draw root node?
        :param int depth:  How many levels we're into the tree
        :return tuple:  Tuple, updated canvas and height of drawn content
        """
        if not node:
            return canvas, 0

        # ignore nodes with a direction we're not rendering right now
        if not node.has_direction(side, inclusive=True):
            return canvas, 0

        # determine how much we want to enlarge the text
        font_size = self.get_font_size(node)

        # determine how high this block will be based on the available
        # height and the nodes we'll need to fit in it
        block_width, block_height = self.get_bbox(node, side)
        own_width, own_height = self.get_bbox(node, side, False)

        if side == self.SIDE_LEFT and node.is_root:
            # first element on the left - start drawing from the right
            x += self.get_bbox(node, side)[0] - own_width

        # keep track of what part of the canvas has been used so far
        self.x_min = min(self.x_min, x)
        self.x_max = max(self.x_max, x + block_width)

        # the 0.55 offset makes it so that the top of lower case letters
        # equals the top of the container i.e. it is a more convenient
        # baseline (roughly equal to the x-height) - by default in svg the
        # bottom of the text is at y=0
        x_height = (font_size * 0.55)
        text_offset_y = x_height
        # adjust positioning depending on alignment setting
        if self.align == "middle":
            # center text vertically in block
            text_offset_y += (block_height * 0.5) - (x_height * 0.5)

        elif self.align == "bottom":
            text_offset_y += block_height - x_height

        # difference between text baseline and bezier connection point
        # gonna be honest here, no idea why this works (why 3.8?)
        origin_offset_y = font_size / 3.8
        node.coordinates = (x, y)
        node.dimensions = (own_width, block_height)
        container = SVG(
            x=f"{x}ch",
            y=f"{y}rem",
            width=f"{own_width}ch",
            height=f"{block_height}rem",
            overflow="visible",
            debug=False,
            id=node.id if (not node.is_root or draw_root) else "",
            parent=node.parent.id if not node.is_root else ""
        )

        if draw_root or not node.is_root:
            # ensure we only draw the root node once
            # we still do everything else for the root node even if it is not
            # drawn, to ensure correct positioning and connecting of the rest
            # of the graph
            colour = self.palette[depth % len(self.palette) + 1]
            container.add(
                Text(
                    text=node.name,
                    insert=(0, f"{text_offset_y}rem"),  # baseline
                    style=f"font-size:{font_size}rem",
                    fill="#000",
                    latent_colour=colour,
                    # filter="url(#debug)",
                    debug=False
                )
            )

        canvas.add(container)

        # draw the line connecting this node to the parent node
        # so far we've worked with relative units which is nice for text
        # but we need absolute coordinates for the bezier curves...
        # we have a reasonably well-working conversion factor though
        gap_guide = 0.1  # space between text and start/end of line
        if origin:
            destination = (
                (x + own_width if side == self.SIDE_LEFT else x) - (self.gap_x * (gap_guide * side)),
                y + text_offset_y - origin_offset_y
            )

            # bezier curve control points
            control_x_offset = (destination[0] - origin[0]) / 5
            control_left_x = destination[0] - control_x_offset
            control_right_x = origin[0] + control_x_offset
            control_left = (control_left_x, origin[1])
            control_right = (control_right_x, destination[1])

            # draw curve
            stroke_width = max(1, font_size * 0.75) * 1.5
            flow = Path(stroke="#000", fill_opacity=0, stroke_linecap="round",
                        stroke_width=stroke_width)
            flow.push(f"M {origin[0] * self.CH_CONV} {origin[1] * self.REM_CONV}")
            flow.push(
                f"C {control_left[0] * self.CH_CONV} {control_left[1] * self.REM_CONV} "
                f"{control_right[0] * self.CH_CONV} {control_right[1] * self.REM_CONV} "
                f"{destination[0] * self.CH_CONV} {destination[1] * self.REM_CONV}"
            )
            canvas.add(flow)

        # bezier curves for the next set of nodes will start at these
        # coordinates (i.e. the left or right side of the text)
        new_origin = (
            ((x + own_width) if side == self.SIDE_RIGHT else x) + (self.gap_x * (gap_guide * side)),
            y + text_offset_y - origin_offset_y,
        )

        # add gap to the next node
        x += self.gap_x * side

        # draw this node's children
        for child in node.children:
            if side == self.SIDE_LEFT:
                # left side: align to the right of the box
                offset_x, _ = child.own_bbox
                offset_x *= side
            else:
                offset_x = own_width

            canvas, child_height = self.render(
                canvas,
                child,
                x=x + offset_x,
                y=y,
                height=height,
                origin=new_origin,
                side=side,
                draw_root=False,
                depth=depth + 1
            )

            y += child_height

        return canvas, block_height

    def get_font_size(self, node: TreeNode) -> float:
        """
        Get font size for a node

        Use a sine-based easing function to not emphasise the top branches
        too much

        :param TreeNode node:  Node to determine font size for
        :return float:  Font size, based on configured global font size
        """
        if node.weight > self.max_weight:
            # this can happen because we use the weight of the *second* most
            # prevalent node as the max weight
            return self.FONT_FACTOR_MAX
        elif self.max_weight == 0:
            # and this can happen if de-tokenisation failed earlier
            return 1

        embiggen = node.weight / self.max_weight if self.max_weight else 1
        embiggen = sin(embiggen * 0.5 * pi)
        return max(1, embiggen * self.FONT_FACTOR_MAX)

    def get_bbox(self, node: TreeNode, direction: int, with_children: bool = True) \
            -> tuple[float, float]:
        """
        Get bounding box of a node

        This is based on the configured font size and by default includes
        space for the node's children to be rendered.

        :param TreeNode node:  Node to determine bounding box of
        :param int direction:  Which direction of the tree to consider
        :param bool with_children:  Include room for children in box?
        :return tuple:  (width, height) dimensions tuple
        """
        bbox_q = (direction, with_children)
        if bbox_q not in node.bbox:
            font_size = self.get_font_size(node)

            own_width = len(node.name)
            for character in node.name:
                if emoji.is_emoji(character):
                    own_width += self.REM_TO_CH  # square instead of rectangular

            own_width *= font_size
            own_height = font_size + self.gap_y
            node.own_bbox = (own_width, own_height)

            branch_height = 0
            branch_width = 0

            if with_children:
                for child in node.children:
                    if not child.has_direction(direction, inclusive=True):
                        continue

                    (child_width, child_height) = self.get_bbox(child, direction)
                    branch_height += child_height
                    branch_width = max(branch_width, child_width)

                own_height = max(branch_height, own_height)
                own_width += branch_width

            node.bbox[bbox_q] = (own_width, own_height)

        return node.bbox[bbox_q]

    def invert_node_labels(self, node: TreeNode):
        """
        Invert the word order in node labels

        Used for nodes on the left side of the tree view, which would be the
        wrong way around otherwise.

        :param TreeNode node:  Node to reverse text for
        """
        if node.has_direction(self.SIDE_LEFT):
            node.name = self.SPACE.join(reversed(node.name.split(self.SPACE)))

        for child in node.children:
            self.invert_node_labels(child)

    def get_svg_script(self) -> str:
        """
        Simple embeddable JavaScript to toggle colouring

        :return str:  Script code
        """
        return """
window.addEventListener('DOMContentLoaded', function () {
    document.querySelector('#toggle-colour').addEventListener('click', function (e) {
        document.querySelectorAll('#tree text').forEach((component) => {
            if (!component.hasAttribute('fill') || component.getAttribute('fill') == '#000') {
                component.setAttribute('fill', component.getAttribute('latent-colour'));
            } else {
                component.setAttribute('fill', '#000');
            }
        });
    });
    document.querySelectorAll('#tree text').forEach((element) => {
      element.addEventListener('click', function(e) {
        let highlight_element = e.target.parentNode;
        if(highlight_element.classList.contains('highlighted')) {
          document.querySelectorAll('.highlighted').forEach((e) => e.classList.remove('highlighted'));
          return;
        }
        if(!highlight_element.hasAttribute('parent')) {
          return;
        }
        while(true) {
          highlight_element.classList.add('highlighted');

          if(!highlight_element.hasAttribute('parent')) {
            break;
          }
          highlight_element = document.getElementById(highlight_element.getAttribute('parent'));
        }
      });
    });
});
"""

    def get_css(self):
        """
        Simple embeddable stylesheet to highlight hovered flows

        :return str:  CSS code
        """
        return """
svg[parent] text {
    cursor: pointer;
}
.highlighted text {
	fill: #F09;
	text-decoration: underline;
}
"""

