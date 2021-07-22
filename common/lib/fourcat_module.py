"""
4CAT Module superclass for DataSets and BasicProcessors
"""
import abc


class FourcatModule(metaclass=abc.ABCMeta):
    """
    4CAT Module superclass

    `DataSet` and `BasicProcessor` descend from this class. This superclass is
    intended primarily to contain functionality that allows one to check
    compatibility between datasets and processors, and processors and other
    processors, agnostic of whether the object being checked is a dataset or
    processor. This reduces boilerplate code in `is_compatible_with` methods
    in processors.
    """
    pass
