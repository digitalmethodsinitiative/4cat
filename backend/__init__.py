"""
The backend module consists of a collection of important submodules that are core to 4CAT.
"""

import sys
import os

from common.lib.module_loader import ModuleCollector

# load modules
all_modules = ModuleCollector()

# add 4CAT root as import path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/..")