"""
Helpers for processors that need all vectors of an embeddings dataset at once.
Mostly to reduce memory errors

"""
import numpy as np

from common.lib.exceptions import ProcessorInterruptedException

# How often to report progress while reading, in items
STATUS_EVERY = 1000


def get_vector(record: dict) -> list:
    """
    Get the embedding of a record as a list of numbers.

    :param dict record:  Embedding record
    :return list:  The vector, or an empty list if the record has none
    """
    vector = record.get("embedding")
    if isinstance(vector, str):
        vector = [float(value) for value in vector.split() if value]
    return vector or []


def read_embedding_matrix(dataset, limit: int, processor=None, accept=None, keep=None) -> tuple:
    """
    Read up to `limit` embeddings into one float32 array.

    The array is allocated once, at its full size, instead of collecting rows
    and stacking them, which would hold every vector twice for a moment.

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
    matrix = None
    positions, kept = [], []

    for position, item in enumerate(dataset.iterate_items(processor, get_annotations=False)):
        if processor is not None and processor.interrupted:
            raise ProcessorInterruptedException("Interrupted while reading embeddings")

        if len(positions) >= limit:
            break

        record = item.original

        if accept is not None and not accept(record):
            continue

        vector = get_vector(record)
        if not vector:
            continue

        if matrix is None:
            matrix = np.empty((limit, len(vector)), dtype=np.float32)
        elif len(vector) != matrix.shape[1]:
            # a ragged matrix cannot be compared; this means the dataset mixes
            # models, which should not happen but is worth saying out loud
            raise ValueError("The embeddings are not all the same size.")

        matrix[len(positions)] = vector
        positions.append(position)
        if keep is not None:
            kept.append(keep(record))

        if processor is not None and len(positions) % STATUS_EVERY == 0:
            processor.dataset.update_status(f"Read {len(positions):,} embeddings")

    if matrix is None:
        return np.empty((0, 0), dtype=np.float32), [], []

    return matrix[:len(positions)], positions, kept


def find_embedding(dataset, match, processor=None):
    """
    Find the first record that matches, and its vector.

    :param dataset:  Embeddings dataset
    :param match:  `function(record) -> bool`
    :param processor:  Processor reading it, to stop when it is interrupted
    :return tuple:  `(vector as float32 array, record)`, or `(None, None)`
    """
    for item in dataset.iterate_items(processor, get_annotations=False):
        if processor is not None and processor.interrupted:
            raise ProcessorInterruptedException("Interrupted while reading embeddings")

        record = item.original
        if match(record):
            vector = get_vector(record)
            if vector:
                return np.asarray(vector, dtype=np.float32), record
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
