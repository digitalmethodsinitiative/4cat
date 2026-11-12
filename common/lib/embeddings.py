"""
Helpers for processors that need all vectors of an embeddings dataset at once.
Mostly to reduce memory errors

"""
import numpy as np

from common.lib.exceptions import ProcessorInterruptedException
from common.lib.user_input import UserInput

# How often to report progress while reading, in items
STATUS_EVERY = 1000

# Read embeddings in batches to avoid memory problems
READ_BATCH = 8192

MAX_EMBEDDINGS = "embeddings.max_embeddings"

# processor queue
EMBEDDING_QUEUE = "embeddings"


def get_max_items(config) -> int:
    """
    The most embeddings a processor may read.

    :param config:  Configuration reader, or `None` if there is none to read
    :return int:  Most embeddings to read, or 0 for no limit
    """
    if config is None:
        return 0

    try:
        return max(0, int(config.get(MAX_EMBEDDINGS, 0) or 0))
    except (TypeError, ValueError):
        return 0


def amount_option(config, tooltip: str, default: int = 0) -> dict:
    """
    The 'No. of items' option capped by admin setting. Follows the image visualisation processors.

    :param config:  Configuration reader, or `None`
    :param str tooltip:  Tooltip saying what a larger number costs
    :param int default:  Number to start the option at
    :return dict:  Option definition
    """
    maximum = get_max_items(config)

    option = {
        "type": UserInput.OPTION_TEXT,
        "help": "No. of items",
        "default": min(default, maximum) if (default and maximum) else default,
        "min": 0,
        "coerce_type": int,
        "tooltip": tooltip + (f" '0' uses all embeddings, up to the {maximum:,} this 4CAT allows."
                              if maximum else " '0' uses all embeddings."),
    }

    if maximum:
        option["max"] = maximum

    return option


def items_to_read(parameters: dict, config, available: int) -> int:
    """
    How many embeddings to read.

    :param dict parameters:  Processor parameters
    :param config:  Configuration reader, or `None`
    :param int available:  Embeddings in the parent dataset
    :return int:  Number of embeddings to read
    """
    wanted = parameters.get("amount", 0) or available
    maximum = get_max_items(config)

    if maximum:
        wanted = min(wanted, maximum)

    return min(wanted, available)


def get_vector(item: dict) -> list:
    """
    Get the embedding of an item as a list of numbers.

    :param dict item:  Embedding item
    :return list:  The vector, or an empty list if the item has none
    """
    vector = item.get("embedding")
    if isinstance(vector, str):
        vector = [float(value) for value in vector.split() if value]
    return vector or []


def merge_batches(batches: list, rows: int, dimensions: int):
    """
    Join the batches read into one array of exactly `rows` rows. Used to make
    sure embeddings are not held in memory twice.

    :param list batches:  Batches of rows, in the order they were read
    :param int rows:  Rows actually filled across all batches
    :param int dimensions:  Width of each row
    :return:  One float32 array of `rows` rows
    """
    if len(batches) == 1:
        # one batch is already the right width; copy only if it has a tail of
        # rows that were never filled, which the caller would otherwise hold on
        # to for as long as it keeps the matrix
        return batches[0] if len(batches[0]) == rows else batches[0][:rows].copy()

    matrix = np.empty((rows, dimensions), dtype=np.float32)
    offset = 0
    while batches:
        # each batch is released as soon as it is copied over, so the two never
        # hold the embeddings at the same time
        batch = batches.pop(0)
        taken = min(len(batch), rows - offset)
        matrix[offset:offset + taken] = batch[:taken]
        offset += taken
        del batch

    return matrix


def read_embedding_matrix(dataset, limit: int, processor=None, accept=None, keep=None) -> tuple:
    """
    Read up to `limit` embeddings into one float32 array.

    Read in batch rather than into one array of `limit` rows: `limit` is a
    ceiling, not a count, and an array allocated at its full size keeps the
    difference for as long as the caller holds the matrix. With an `accept`
    that leaves most of the dataset out, that difference is nearly all of it.

    :param dataset:  Embeddings dataset
    :param int limit:  Most embeddings to read
    :param processor:  Processor reading it, for progress and interruption
    :param accept:  Optional `function(record) -> bool`; records it rejects
      are skipped
    :param keep:  Optional `function(record) -> anything`, to keep a small
      summary of each record read (never the vector itself)
    :return tuple:  `(matrix, positions, kept)`: one row per embedding read;
      the position of each among the items `iterate_items()` yields, to find
      them again in a second pass; and what `keep` returned for each (empty
      without `keep`)
    :raises ValueError:  If the embeddings are not all the same size
    """
    batches, rows, dimensions = [], 0, None
    positions, kept = [], []

    for position, item in enumerate(dataset.iterate_items(processor, get_annotations=False)):
        if processor is not None and processor.interrupted:
            raise ProcessorInterruptedException("Interrupted while reading embeddings")

        if rows >= limit:
            break

        record = item.original

        if accept is not None and not accept(record):
            continue

        vector = get_vector(record)
        if not vector:
            continue

        if dimensions is None:
            dimensions = len(vector)
        elif len(vector) != dimensions:
            # embeddings shouldn't have different lenghts, something is up!
            raise ValueError("The embeddings are not all the same size.")

        if rows % READ_BATCH == 0:
            # never more rows than are still wanted, so a nearly reached limit
            # does not allocate a whole batch for a handful of vectors
            batches.append(np.empty((min(READ_BATCH, limit - rows), dimensions), dtype=np.float32))

        batches[-1][rows % READ_BATCH] = vector
        rows += 1
        positions.append(position)
        if keep is not None:
            kept.append(keep(record))

        if processor is not None and rows % STATUS_EVERY == 0:
            processor.dataset.update_status(f"Read {rows:,} embeddings")

    if not rows:
        return np.empty((0, 0), dtype=np.float32), [], []

    return merge_batches(batches, rows, dimensions), positions, kept


def find_embedding(dataset, match, processor=None):
    """
    Find the first item that matches, and its vector.

    :param dataset:  Embeddings dataset
    :param match:  `function(item) -> bool`
    :param processor:  Processor reading it, to stop when it is interrupted
    :return tuple:  `(vector as float32 array, item)`, or `(None, None)`
    """
    for item in dataset.iterate_items(processor, get_annotations=False):
        if processor is not None and processor.interrupted:
            raise ProcessorInterruptedException("Interrupted while reading embeddings")

        item = item.original
        if match(item):
            vector = get_vector(item)
            if vector:
                return np.asarray(vector, dtype=np.float32), item
    return None, None


def normalise_in_place(matrix):
    """
    Scale each row to length 1, without making a copy.

    Embeddings are compared by angle (cosine similarity), not length. On unit
    vectors, Euclidean distances and dot products follow the angles.

    :param matrix:  2D float array, one embedding per row; changed in place
    :return:  The same array
    """
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    matrix /= norms
    return matrix
