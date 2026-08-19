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

## Settings
An extension can add its own settings to 4CAT's settings panel. Declare them in a `config` dictionary on the worker or
processor class:

```python
class MyProcessor(BasicProcessor):
    type = "my-processor"

    config = {
        "my_extension.api_key": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "API key",
            "tooltip": "Get one from the service's developer console"
        }
    }
```

Read them with `self.config.get("my_extension.api_key")`.

Note that the `config` must be on the class, not on a data source's `__init__.py` - a data source's settings belong on
its search or import worker, which 4CAT collects along with every other worker.

### Naming
Put your settings under a prefix of your own. By default the part before the first `.` decides which tab they appear
under, so related settings sharing a prefix are grouped together. Your extension's own id, as in the
`my_extension.api_key` example above, is the safe choice - nothing else will be using it.

Some namespaces are reserved for 4CAT itself, and a setting declared in one of them will be **refused**: `privileges.`,
`flask.`, `4cat.`, `path.`, `datasources.`, `extensions.` and `logging.`. This is so that an extension cannot claim a
name 4CAT might use in a future version, and thereby take over its definition. Note that `extensions.` is among them
despite how it reads: it belongs to 4CAT's own settings *about* extensions, not to your extension's settings.

A setting that a 4CAT release already declares is also refused - 4CAT's own definition always wins. Where two extensions
declare the same setting, the first one wins, and which is 'first' does not depend on the machine. Refusals are written
to the 4CAT log, so if a setting of yours does not show up, look there first.

Several classes sharing a base class that declares `config` is fine: the setting is registered once, and inheriting it
is not treated as a collision.

### Where a setting appears
A setting's tab is the part of its name before the first `.`, and that tab is listed under a heading matching where the
setting was declared - 'Extensions' for anything an extension declares. Note that this is decided per *tab*, not per
setting, and 4CAT's own settings win: a tab that also holds a core setting is listed under '4CAT Core', including
anything your extension put in it. Give your settings a prefix of your own and the question does not arise. Three
optional keys override that:

- `"category"` puts the setting in a named tab whatever its name is, which is how settings declared across several
  classes end up in one place.
- `"category_label"` titles that tab. Without one, 4CAT falls back to its own list of category names, then to the
  category itself.
- `"submenu"` lists the tab under a different heading: `core`, `datasources`, `processors` or `extensions`.

The last two describe the *tab*, not the setting, so declaring either on any one setting applies to the whole tab and
the first declaration wins. They are also the only way to name or place a tab 4CAT does not already know about, since
its own category list cannot be added to from outside.

### Settings that your code writes
If a setting holds something your worker maintains rather than something an administrator sets - a cache timestamp, a
list of options fetched from an API - mark it `"indirect": True`. It will then be kept out of the settings form, so it
cannot be edited or overwritten by someone saving that page.

### What happens to settings when an extension goes away
4CAT does not delete an extension's settings. If your extension is switched off or uninstalled, its stored values are
kept, and enabling or re-installing it restores the previous configuration instead of reverting to defaults. While the
extension is not loaded, its settings are listed under 'unused settings' in the control panel, marked as kept on
purpose.

This means you do not need to worry about an administrator losing their configuration across an upgrade that briefly
removes your extension. It also means that renaming one of your settings leaves the old value behind; 4CAT will not
clean that up for you, because it cannot tell a rename from an uninstall.

### Applying changes
Declarations are read once, when the 4CAT back-end starts, and cached. After adding, renaming or removing a setting in
your code, restart 4CAT before expecting the change in the interface.
