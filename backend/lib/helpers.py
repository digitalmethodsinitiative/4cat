"""
Miscellaneous helper functions for the 4CAT backend
"""
import os


def get_absolute_folder(folder):
    """
    Get absolute path to a folder

    Determines the absolute path of a given folder, which may be a relative
    or absolute path. Note that it is not checked whether the folder actually exists

    :return string:  Absolute folder path (no trailing slash)
    """
    if len(folder) == 0 or folder[0] != "/":
        path = os.path.dirname(os.path.dirname(os.path.dirname(__file__))) + "/"  # 4cat root folder
        path += folder
    else:
        path = folder

    path = path[:-1] if len(path) > 0 and path[-1] == "/" else path

    return path
