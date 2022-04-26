"""
Search HTML for scripts in matching tracking tools

NOTE: expects a file called bugs.json to be located in common\assets\
"""
import os
import csv

from backend.abstract.processor import BasicProcessor
from common.lib.helpers import UserInput
import config

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class DetectTrackers(BasicProcessor):
    """
    Detect tracker scripts (from a collection) within collected HTML
    """
    type = "tracker-filter"  # job type ID
    category = "Filtering"  # category
    title = "Detect Trackers"  # title displayed in UI
    description = "Uses a collection of scripts identified as belonging to" \
                  " different trackers and detects them in HTML. " \
                  "This will create a new dataset."
    extension = "csv"  # extension of result file, used internally and in UI

    options = {
        "column": {},
        "record-matches": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Create True/False column for each match string",
            "default": "no",
            "options": {
                "yes": "Yes, create a column for each tracker",
                "no": "No, summary column only"
            },
            "tooltip": "A column is created for each tracker and marked True " \
                       "if value was found in column. Otherwise only a summary " \
                       "column is created listing detected trackers."
        }
    }

    tracker_file = os.path.join(config.PATH_ROOT, 'common/assets/bugs.json')

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on datasets.

        Note: It only makes sense to run on HTML. We may wish to make this more
        specific.

        :param module: Dataset or processor to determine compatibility with
        """
        return os.path.isfile(cls.tracker_file) and module.is_top_dataset()

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):

        options = cls.options
        if not parent_dataset:
            return options
        parent_columns = parent_dataset.get_columns()

        if parent_columns:
            parent_columns = {c: c for c in sorted(parent_columns)}
            options["column"] = {
                "type": UserInput.OPTION_CHOICE,
                "options": parent_columns,
                "default": "html" if "html" in parent_columns else "body",
                "help": "Dataset column containing HTML"
        }

        return options

    def process(self):
        """
        Reads a dataset, filtering items that match in the required way, and
        creates a new dataset containing the matching values
        """

        column = self.parameters.get("column", "")
        match_style = 'contains'
        match_multiple = 'any'
        match_function = any if match_multiple == "any" else all
        record_matches = True if self.parameters.get("record-matches") == 'yes' else False

        self.dataset.update_status('Loading trackers...')
        trackers = self.load_trackers(self.tracker_file)
        tracker_names = list(set([trackers[tracker]['name'] for tracker in trackers]))
        self.dataset.update_status('Loaded %i trackers.' % len(trackers))

        self.dataset.log('Searching for trackers in column %s' % column)
        matching_items = 0
        processed_items = 0
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            writer = None

            for item in self.source_dataset.iterate_items(self):
                if not writer:
                    # first iteration, check if column actually exists
                    if column not in item.keys():
                        self.dataset.update_status("Column '%s' not found in dataset" % column, is_final=True)
                        self.dataset.finish(0)
                        return

                    if record_matches:
                        fieldnames = list(item.keys()) + ['tracker_summary'] + tracker_names
                    else:
                        fieldnames = item.keys() + ['tracker_summary']
                    # initialise csv writer - we do this explicitly rather than
                    # using self.write_items_and_finish() because else we have
                    # to store a potentially very large amount of items in
                    # memory which is not a good idea
                    writer = csv.DictWriter(outfile, fieldnames=fieldnames)
                    writer.writeheader()

                processed_items += 1
                if processed_items % 500 == 0:
                    self.dataset.update_status("Processed %i items (%i with trackers detected)" % (processed_items, matching_items))

                # Get column to be used in search for matches
                item_column = item.get(column)

                # Compare each tracker with item_column
                item['tracker_summary'] = {}
                for tracker in trackers:
                    if tracker in item_column:
                        # Add to summary
                        if trackers[tracker]['type'] in item['tracker_summary'].keys():
                            # add to summary
                            item['tracker_summary'][trackers[tracker]['type']].append(trackers[tracker]['name'])
                        else:
                            # start summary
                            item['tracker_summary'][trackers[tracker]['type']] = [trackers[tracker]['name']]
                        # Add to tracker column
                        if record_matches:
                            if trackers[tracker]['name'] in item.keys():
                                # already one tracker with that name identified
                                item[trackers[tracker]['name']] = item[trackers[tracker]['name']] + ',' + tracker
                            else:
                                # first tracker of that name
                                item[trackers[tracker]['name']] = tracker
                # Record entry
                if item['tracker_summary']:
                    writer.writerow(item)
                    matching_items += 1

        if matching_items == 0:
            self.dataset.update_status("No items matched your criteria", is_final=True)

        self.dataset.finish(matching_items)

    def after_process(self):
        super().after_process()

        # Request standalone
        self.create_standalone()

    # TODO: Look at better way to load the trackers; this seems to not use all available trackers
    def load_trackers(self, location_of_tracker_file):
        """
        This takes a json database of scripts and names of the company/organization
        that uses them and reformats it to be used by our script. This may be
        unnecessary, but it already existed (https://github.com/digitalmethodsinitiative/tools/blob/master/beta/trackerTracker/ghostery/update.py)
        so porting seemed easier.
        """
        from collections.abc import MutableMapping
        import json

        def merge(x, y):
            """
            Makes a shallow copy of an origin dictionary and update it with another.
            :param x: First dictionary to merge
            :type x: Dictionary
            :param y: Second dictionary to merge
            :type y: Dictionary
            :return: Returns a merged dictionary
            :rtype: Dictionary
            """
            z = x.copy()
            z.update(y)

            return z

        def flatten(d, o, parent=''):
            """
            Flatten dictionary to a keyvalue pair. The key will be a dot notated string containing the nested keys of a dictionary.
            This will be a domain/hostname. The value will contain the bug id (cid).
            :param d: Dictionary to flatten
            :type d: Dictionary
            :param o: Type of conversion
            :type o: String
            :param parent: Optional parameter for passing the previously flatten dictionary path.
            :return: Returns a list of keyvalue pairs containing domains/hostnames: cid
            :rtype: List
            """
            items = []
            for k, v in d.items():
                new = parent + '.' + k if parent else k
                if isinstance(v, MutableMapping):
                    items.extend(flatten(v, o, new).items())
                else:
                    if o == 'host':
                        split = new.split('.')[:-1]
                        split.reverse()

                        #pattern = '\\.'.join(split)
                        pattern = '.'.join(split)
                        cid = v

                        items.append((pattern, cid))

                    elif o == 'host_path':
                        split = new.split('.')[:-1]
                        split.reverse()

                        #pattern = '\\.'.join(split)
                        pattern = '.'.join(split)
                        for p in v:
                            #path = pattern + '\\/' + p['path']
                            path = pattern + '/' + p['path']
                            items.append((path, p['id']))

                    elif o == 'first_party':
                        self.dataset.log("unknown tracker path type: %s" % str(v))


            return dict(items)

        with open(location_of_tracker_file) as update:
            data = json.load(update)
            apps = data['apps']
            bugs = data['bugs']
            patterns = data['patterns']

        tracker_dictionary = {}

        host = flatten(patterns['host'], 'host')
        host_path = flatten(patterns['host_path'], 'host_path')

        items = merge(host, host_path)
        for index, (key, value) in enumerate(items.items()):
            aid = bugs[str(value)]['aid']
            name = apps[str(aid)]['name']
            cat = apps[str(aid)]['cat']

            tracker_dictionary[key] = {
                    "id": index,
                    "aid": aid,
                    "cid": value,
                    "name": name,
                    "type": cat,
                    }
        with open(self.tracker_file.rstrip('.json.') + '_update.json', 'w') as outfile:
            json.dump(tracker_dictionary, outfile)
        return tracker_dictionary
