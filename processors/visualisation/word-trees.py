"""
Generate word tree from dataset
"""
import string
import jieba
import re

from backend.lib.processor import BasicProcessor
from common.lib.helpers import UserInput, convert_to_int, get_4cat_canvas
from common.lib.exceptions import QueryParametersException

from nltk.tokenize import word_tokenize

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
    weight = None

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

    def without_query(self, query: list) -> list:
        """
        Get the fragment value without the query

        Depending on the direction, removes the first or last tokens of the
        fragment that contain the original query.

        :param list query:  Query, as a list of tokens
        :return list:  Remaining tokens
        """
        value = reversed(self.value) if self.direction == MakeWordtree.SIDE_LEFT else self.value
        return list(value)[len(query):]

class WildcardMatcher:
    """
    Plumbing for matching wildcard (* and ?) strings
    """
    # can't really think of a better way than this
    dictionary = {
        "*": "OOOOOXXOOOOOXXOOOOOXXOOOOOASTERISKOOOOOXXOOOOOXXOOOOOXXOOOOO",
        "?": "OOOOOXXOOOOOXXOOOOOXXOOOOOQMARKOOOOOXXOOOOOXXOOOOOXXOOOOO",
    }

    @staticmethod
    def obfuscate(q: str) -> str:
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

    @staticmethod
    def deobfuscate(q: str) -> str:
        """
        Deobfuscate a wildcard string

        :param str q:
        :return str:
        """
        for s, r in WildcardMatcher.dictionary.items():
            q = q.replace(r, s)
        return q

    @staticmethod
    def compile(q: str) -> re.Pattern:
        """
        Compile a regular expression for matching

        Escapes all regex syntax currently in the match string.

        :param str q:
        :return re.Pattern:
        """
        q = WildcardMatcher.obfuscate(q)
        q = re.escape(q)
        q = WildcardMatcher.deobfuscate(q)
        q = q.replace("*", ".*?").replace("?", ".")
        return re.compile(q)


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

    references = [
        "Wattenberg, M., & Viégas, F. B. (2008). [The Word Tree, an Interactive Visual Concordance](https://doi.org/10.1109/TVCG.2008.172). IEEE Transactions on Visualization and Computer Graphics, 14(6), 1221–1228."
    ]

    # can be changed
    FONT_SIZE = 14  # in px
    FONT_FACTOR_MAX = 3  # how big can the font get?

    # will be adjusted based on tokeniser used
    SPACE = ""

    # convert between relative and absolute units
    REM_CONV = FONT_SIZE
    CH_CONV = FONT_SIZE * 0.601875

    # gaps between nodes vertically and horizontally
    gap_x = 4
    gap_y = 1

    # to be used later to determine dimensions of graph
    x_min = 0
    x_max = 0

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
                "tooltip": "Enter a word here to serve as the root of the word tree. The context of this query will be mapped in the tree visualisation. Cannot be empty. You can use wildcards: 'politic*' will match 'politician' and 'politics' for example.",
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
                "default": 15,
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
                "default": "regular",
                "options": {
                    "regular": "nltk word_tokenize",
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
            },
            "lower-case": {
                "type": UserInput.OPTION_TOGGLE,
                "default": True,
                "help": "Make all text lower case",
                "tooltip": "If not checked, e.g. 'The' and 'the' will be considered separate branches of the word tree"
            },
            "stop-sentences": {
                "type": UserInput.OPTION_TOGGLE,
                "default": False,
                "help": "Stop at period",
                "tooltip": "If selected, tree branches will stop at a period (i.e. the end of a sentence), even if the "
                           "branch is shorter than the Window size. This only affects the right side of the tree "
                           "(after the query)"
            },
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

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor to run on all csv and NDJSON datasets

        :param module: Dataset or processor to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return module.get_extension() in ("csv", "ndjson")

    def process(self):
        """
        This takes a 4CAT results file as input, and outputs a plain text file
        containing all post bodies as one continuous string, sanitized.
        """
        align = self.parameters.get("align")
        sides = self.parameters.get("sides")

        # nice label
        self.dataset.update_label(f"Word tree: '{self.parameters.get('query')}'")

        # build our tree of text fragments
        root, max_weight = self.build_tree(self.parameters.get("query"))

        if not root or not root.children:
            return self.dataset.finish_with_error(f"Query '{self.parameters.get('query')} not found in dataset")

        # while we're at it, we also calculate the (approximate) dimensions of
        # each branch, which we will need for rendering it later
        width_left, height_left = self.get_bbox(root, max_weight, self.SIDE_LEFT)
        width_right, height_right = self.get_bbox(root, max_weight, self.SIDE_RIGHT)
        width, height = sum([width_left, width_right]), max(height_left, height_right)

        # depending on which side of the tree is higher, we need to adjust the
        # height of the other side; and we need to decide which side of the
        # tree gets to draw the root node, since we can't have both sides draw
        # it
        origin_left_y, origin_right_y = 0, 0
        root_side = "right" if sides == "only-right" else "left"
        if sides == "both":
            root_side = "right" if height_right > height_left else "left"

        if align == "middle":
            if height_left > height_right:
                origin_right_y = int((height / 2) - (height_right / 2))
            else:
                origin_left_y = int((height / 2) - (height_left / 2))
        elif align == "bottom":
            origin_right_y = height - height_right
            origin_left_y = height - height_left

        # the nodes on the left side of the graph now have the wrong word order,
        # because we reversed them earlier to generate the correct tree
        # hierarchy - now reverse the node labels so they are proper language
        # again
        self.invert_node_labels(root)

        self.dataset.update_status(f"Rendering tree to SVG file (root side: {root_side})")
        wrapper = SVG(overflow="visible", debug=False)
        offset_x = 0

        if sides != "only-right":
            self.dataset.update_status("Adding left side of tree to SVG file")
            wrapper, _ = self.render(
                wrapper,
                root,
                y=origin_left_y,
                height=height,
                side=self.SIDE_LEFT,
                max_weight=max_weight,
                draw_root=root_side == "left"
            )

            # shift the rest of the tree to the right of this half
            offset_x += width_left - self.get_bbox(root, max_weight, self.SIDE_LEFT, False)[0]

        if sides != "only-left":
            self.dataset.update_status("Adding right side of tree to SVG file")
            wrapper, _ = self.render(
                wrapper,
                root,
                x=offset_x,
                y=origin_right_y,
                height=height,
                side=self.SIDE_RIGHT,
                max_weight=max_weight,
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
        canvas.add(Rect((25, canvas["height"] - 25 - 25), (25, 25), fill=self.palette[0], style="cursor:pointer", id="toggle-colour", stroke="#000"))
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
            tokeniser_args = {}
        else:
            self.SPACE = " "
            tokeniser = word_tokenize

        # tokenise query
        if lowercase:
            query = query.lower()
        tokenised_query = tokeniser(WildcardMatcher.obfuscate(query), **tokeniser_args)
        tokenised_query = [WildcardMatcher.deobfuscate(q) for q in tokenised_query]
        if type(tokenised_query) is not list:
            tokenised_query = list(tokenised_query)
        query_token_length = len(tokenised_query)

        def wildcard_match(needle: list, haystack: list):
            for k in range(len(needle)):
                pattern = WildcardMatcher.compile(needle[k])
                if needle[k] != haystack[k] and not pattern.match(haystack[k]):
                    return False
            return True

        def list_in_list(needle: list, haystack: list):
            for k in range(len(haystack)):
                if wildcard_match(needle, haystack[k:k+len(needle)]):
                    yield k

        # find matching posts
        processed = 0
        fragments = []
        columns = self.parameters.get("columns", [])
        if type(columns) is not list:
            columns = [columns]
        link_regex = re.compile(r"https?://\S+")
        for post in self.source_dataset.iterate_items():
            processed += 1
            if processed % 500 == 0:
                self.dataset.update_status(f"Finding query in {processed:,} of {self.source_dataset.num_rows:,} items ({len(fragments):,} matches)")

            for column in columns:
                document = post.get(column)

                try:
                    document = str(document)
                except TypeError:
                    continue

                if self.parameters.get("strip-urls"):
                    document = link_regex.sub("", document)

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
                        fragment = tokenised_query + document[position + query_token_length:position + window + query_token_length - 1]
                        fragments.append(Fragment(fragment, self.SIDE_RIGHT))
                    if sides != "only-right":
                        fragment = document[position - window + 1:position] + tokenised_query
                        fragments.append(Fragment(fragment, self.SIDE_LEFT))

        # terminate fragments at sentence stops, though only on the right side
        # of the tree
        if self.parameters.get("stop-sentences"):
            filtered_fragments = []
            for fragment in fragments:
                if fragment.direction == self.SIDE_LEFT:
                    filtered_fragments.append(fragment)
                    continue

                filtered_fragment = Fragment([], fragment.direction)
                for token in fragment.value:
                    filtered_fragment.value.append(token)
                    if token.endswith("."):
                        break
                filtered_fragments.append(filtered_fragment)

            fragments = filtered_fragments

        # now we no longer need punctuation, we can strip it from the fragments
        # this may leave us with empty fragments, so these are also removed
        punkt_replace = re.compile(r"[" + re.escape(string.punctuation) + "]")
        if self.parameters.get("strip-symbols"):
            for i, fragment in enumerate(fragments):
                for j, token in enumerate(fragment.value):
                    fragment.value[j] = punkt_replace.sub("", token)

                fragment.value = [_ for _ in fragment.value if _.strip()]
                fragments[i] = fragment

        # here is our tree's root node (token)
        root = TreeNode(tokenised_query[0])
        query_start = root
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

            for token in fragment.without_query(tokenised_query):
                child_node = current_node.get_child(token, fragment.direction)
                if not child_node:
                    child_node = TreeNode(token, parent=current_node, direction=fragment.direction)

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
                for grandchild in consolidated_node.children:
                    grandchild.parent = node

                node.children = [child for child in node.children if child != consolidated_node]
                directional_children = [n for n in node.children if
                                        not side or node.has_direction(side, inclusive=True)]

            for child in node.children:
                consolidate(child, side=side)

        consolidate(root)

        # if the query is multi-token, it has not been consolidated if the
        # tree goes in two directions (since all nodes will have branches in
        # two directions), so do so as a special case
        consolidate(root, self.SIDE_RIGHT)

        # now we count how often each node occurs
        # this is quite expensive, iterating through the whole dataset again
        # but when we iterated the first time, we didn't know what the nodes
        # would look like in the end...
        # another issue: we don't really know what the non-tokenised string
        # looked like, so we guesstimate by joining by some space character
        # this is likely to be off the mark for e.g. chinese text
        def walk_and_count(node, document: str, prefix: list, matcher: None|re.Pattern):
            if node.weight is None:
                node.weight = 0

            if node.has_direction(self.SIDE_RIGHT):
                match = f"{self.SPACE.join([*prefix, node.name])}"
            else:
                match = f"{self.SPACE.join([node.name, *prefix])}"

            node.weight += len(matcher.findall(document)) if matcher else document.count(match)
            for child in node.children:
                walk_and_count(child, document, [*prefix, node.name], matcher)

        matcher = WildcardMatcher.compile(query) if bool(re.findall(r"[*?]", query)) else None
        walked = 1
        for item in self.source_dataset.iterate_items():
            if walked % 500 == 0:
                self.dataset.update_status(f"Counting occurrences in item {walked:,} of {self.source_dataset.num_rows:,} items")
            for column in columns:
                document = item.get(column)
                walk_and_count(root, document, [], matcher)
            walked += 1

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
            max_weight: int = 0,
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
        :param int max_weight:  Global max weight of node
        :param int depth:  How many levels we're into the tree
        :return tuple:  Tuple, updated canvas and height of drawn content
        """
        if not node:
            return canvas, 0

        # ignore nodes with a direction we're not rendering right now
        if not node.has_direction(side, inclusive=True):
            return canvas, 0

        # determine how much we want to enlarge the text
        font_size = self.get_font_size(node, max_weight)

        # determine how high this block will be based on the available
        # height and the nodes we'll need to fit in it
        parent_node = node.parent if not node.is_root else node
        own_width, own_height = self.get_bbox(node, max_weight, side, with_children=False)
        block_width, block_height = self.get_bbox(node, max_weight, side)

        if side == self.SIDE_LEFT and node.is_root:
            # first element on the left - start drawing from the right
            x += self.get_bbox(parent_node, max_weight, side, with_children=True)[0] - own_width

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
        if self.parameters.get("align") == "middle":
            # center text vertically in block
            text_offset_y += (block_height * 0.5) - (x_height * 0.5)

        elif self.parameters.get("align") == "bottom":
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
                offset_x, _ = self.get_bbox(child, max_weight, side, False)
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
                max_weight=max_weight,
                depth=depth + 1
            )

            y += child_height

        return canvas, block_height

    def get_font_size(self, node: TreeNode, max_weight: int) -> float:
        """
        Get font size for a node

        Use a sine-based easing function to not emphasise the top branches
        too much

        :param TreeNode node:  Node to determine font size for
        :param int max_weight:  Global max weight to normalise against
        :return float:  Font size, based on configured global font size
        """
        if node.weight > max_weight:
            # this can happen because we use the weight of the *second* most
            # prevalent node as the max weight
            return self.FONT_FACTOR_MAX
        elif max_weight == 0:
            # and this can happen if de-tokenisation failed in walk_and_count
            return 1

        embiggen = node.weight / max_weight if max_weight else 1
        embiggen = sin(embiggen * 0.5 * pi)
        return max(1, embiggen * self.FONT_FACTOR_MAX)

    def get_bbox(self, node: TreeNode, max_weight: int, direction: int, with_children: bool = True) -> tuple[float, float]:
        """
        Get bounding box of a node

        This is based on the configured font size and by default includes
        space for the node's children to be rendered.

        :param TreeNode node:  Node to determine bounding box of
        :param int max_weight:  Global max weight to normalise against
        :param int direction:  Which direction of the tree to consider
        :param bool with_children:  Include room for children in box?
        :return tuple:  (width, height) dimensions tuple
        """
        font_size = self.get_font_size(node, max_weight)

        own_width = len(node.name) * font_size
        own_height = font_size + self.gap_y

        branch_height = 0
        branch_width = 0

        if with_children:
            for child in node.children:
                if not child.has_direction(direction, inclusive=True):
                    continue

                (child_width, child_height) = self.get_bbox(child, max_weight, direction)
                branch_height += child_height
                branch_width = max(branch_width, child_width)

        own_height = max(branch_height, own_height)
        own_width += branch_width

        return own_width, own_height

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
        document.querySelectorAll('text').forEach((component) => {
            if (!component.hasAttribute('fill') || component.getAttribute('fill') == '#000') {
                component.setAttribute('fill', component.getAttribute('latent-colour'));
            } else {
                component.setAttribute('fill', '#000');
            }
        });
    });
    document.querySelectorAll('text').forEach((element) => {
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

