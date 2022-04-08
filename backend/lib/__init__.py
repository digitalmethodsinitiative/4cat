"""
Backend functions to assist in vital functions such as interfacing with the mysql-db, and the workmanager that
manages jobs and workers
"""
import sys, os


# config
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)) + "/../..")