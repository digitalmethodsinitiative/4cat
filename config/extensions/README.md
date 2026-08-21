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
├─ config/
|  ├─ extensions/
│    ├─ my_extension/
│      ├─ my_processor.py
│      ├─ my_other_processor.py
│      ├─ datasources/
│        ├─ my_datasource/
│          ├─ __init__.py
│          ├─ DESCRIPTION.md
│          ├─ search_my_datasource.py
```

In this scenario, `my_extension` would be a git repository within which all other files are contained.

## Settings your extension declares

A processor or data source worker can declare its own settings by putting a `config` dict on the class. 4CAT collects
those when it starts and shows them in the control panel alongside its own.

A setting name has to be unique across the whole of 4CAT, so some declarations are refused:

- A name 4CAT itself already uses is refused. 4CAT's own definition of a setting decides how a saved value is checked,
  what applies when nothing is saved, and whether values set per user group count at all, so an extension cannot be
  allowed to change it.
- Some names are reserved for 4CAT even where it does not use them yet: anything starting with `privileges.`,
  `flask.`, `4cat.`, `path.`, `datasources.`, `extensions.` or `logging.`. Note `extensions.` is among them despite
  how it reads - those are 4CAT's own settings *about* extensions, not your extension's settings.
- Where two modules declare the same name, the first one keeps it, and 4CAT's own modules go first. So an extension
  cannot take a name a built-in processor or data source declares.

Several classes sharing a base class that declares `config` is fine: the setting is registered once, and inheriting it
is not treated as a clash.

Refusals are written to the 4CAT log, naming the module responsible. If a setting of yours does not appear in the
control panel, look there first. Giving your settings a prefix of your own - `my_extension.api_key` rather than
`api_key` - avoids the question entirely.

The same goes for two other names that have to be unique: a worker's `type` and a data source's `DATASOURCE`. If your
extension reuses one that 4CAT already has, 4CAT keeps its own and yours is not loaded, again with a line in the log.
