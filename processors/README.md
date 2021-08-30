# Processors

Processors are modules for 4CAT that take a dataset as their input and 
produce another dataset as their output.

They are self-contained Python files using a common API. Refer to the 
source code (`backend/abstract/processor.py`) and the 
[Wiki](https://github.com/digitalmethodsinitiative/4cat/wiki/How-to-make-a-processor)
for more information on how to make a processor.
Also see our [list of processors on the Wiki](https://github.com/digitalmethodsinitiative/4cat/wiki/Available-processors) for an overview.

All python files contained in this folder can be used as processors via the
4CAT web interface, provided they implement the proper methods and API. The
folder substructure within this folder is for convenience only: it can be used
to organise processor files but has no bearing on how they are displayed in the
web interface or elsewhere.
