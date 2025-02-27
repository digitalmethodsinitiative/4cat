This folder contains 4CAT extensions.

Extensions are processor or data sources that are not part of the main 4CAT codebase, but are otherwise compatible 
with it. For example, a processor that interfaces with a closed API would not be useful to most 4CAT users, but if you
have access to it, you could add such a processor to 4CAT as an extension.


## Installation
Extensions are simply folders within this 'extensions' folder in which Python files containing the relevant code is 
contained. It is strongly recommended that you use git for version control of these folders. Simply commit the code to
a repository somewhere, then clone it into this folder like so:

```shell
cd [4cat root]
cd extensions
git clone [repository URL]
```

This ensures that any dataset created with processors in your extension will be aware of the version of the code they
were created with. This helps debugging and doing reproducible and traceable research.

## Structure
Processors can simply be .py files in the extension folder. Data sources should be sub-folders in a "datasources" 
folder. An extension containing both processors and a data source could look like this:

```
[4CAT root]/
├─ extensions/
│  ├─ my_extension/
│     ├─ my_processor.py
│     ├─ my_other_processor.py
│     ├─ datasources/
│        ├─ my_datasource/
│           ├─ __init__.py
│           ├─ DESCRIPTION.md
│           ├─ search_my_datasource.py
```

In this scenario, `my_extension` would be a git repository within which all other files are contained. 