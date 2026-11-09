"""
Replace author information in collected items

4CAT can hide the people behind the items it collects in two ways. It can
replace their details with a hash, which makes the original value unreadable
but still lets you see that two items came from the same person. Or it can
replace their details with the word REDACTED, which removes that link as well.

Both are offered when creating a dataset and by the 'Pseudonymise or anonymise'
processor. Both use the class below, so that the same mode and the same field
list give the same result wherever they are applied.
"""
import fnmatch
import hashlib
import secrets

from common.lib.helpers import HashCache, dict_search_and_update


class AuthorInfoReplacer:
    """
    Replace the values of fields that identify the author of an item

    Fields are chosen by name, using patterns such as `author*` that may
    contain wildcards. Items are stored in whatever shape the platform sent
    them, so the names that hold author information differ per data source; a
    data source that uses other names can say so with a `pseudonymise_fields`
    attribute on its worker.

    Choosing fields by name only covers the names we know to look for. An
    author name written inside the text of a post, for example, is left alone.
    """

    # Replace values with a hash of the original value
    PSEUDONYMISE = "pseudonymise"

    # Replace values with `REDACTED`
    ANONYMISE = "anonymise"

    # The modes this class understands
    MODES = (PSEUDONYMISE, ANONYMISE)

    # Written in place of a value when it is removed instead of hashed
    REDACTED = "REDACTED"

    # Patterns used when no field list is given
    DEFAULT_FIELDS = ("author*", "user*")

    def __init__(self, mode, fields=None, salt=None):
        """
        :param str mode:  `pseudonymise` to hash values, `anonymise` to replace
        them with `REDACTED`.
        :param fields:  Field name patterns to replace, as a list or as a
        single comma-separated string. `DEFAULT_FIELDS` is used if empty.
        :param salt:  Value mixed into the hash, as bytes or a string. A random
        one is used if not given, which means the same name gets a different
        hash in every dataset. Pass a fixed value to make hashes comparable
        between datasets. Not used when replacing values with `REDACTED`.
        :raises ValueError:  If the mode is not one of `MODES`.
        """
        if mode not in self.MODES:
            raise ValueError(f"Unknown mode '{mode}' for {self.__class__.__name__}; "
                             f"expected one of {', '.join(self.MODES)}")

        self.mode = mode
        self.fields = self.parse_fields(fields)

        #: How many values have been replaced so far
        self.replaced = 0

        # which names in a given set of field names match the patterns, so the
        # patterns are compared to a set of names only once
        self._matches = {}

        self.hash_cache = None
        if self.mode == self.PSEUDONYMISE:
            # BLAKE2b is used for its speed, since a large dataset may need a
            # hash for every item
            if salt is None:
                salt = secrets.token_bytes(16)
            elif isinstance(salt, str):
                salt = salt.encode("utf-8")

            hasher = hashlib.blake2b(digest_size=24)
            hasher.update(salt)
            self.hash_cache = HashCache(hasher)

    @classmethod
    def parse_fields(cls, fields):
        """
        Read a field list as given by a user or a data source

        :param fields:  A list of patterns, or a single comma-separated string
        of them. Empty values fall back to `DEFAULT_FIELDS`.
        :return list:  Patterns, trimmed and in lower case
        """
        if not fields:
            fields = cls.DEFAULT_FIELDS

        if isinstance(fields, str):
            fields = fields.split(",")

        # nested items are matched with dict_search_and_update(), which
        # compares lower case patterns, so use lower case here too and both
        # shapes look for the same names
        return [field.strip().lower() for field in fields if field.strip()]

    def replace(self, value):
        """
        Get what a single value should be replaced with

        Every replacement passes through here, whether the item was flat or
        nested, so this is also where they are counted.

        :param value:  Original value
        :return:  A hash of the value, or `REDACTED`
        """
        self.replaced += 1

        if self.mode == self.ANONYMISE:
            return self.REDACTED

        return self.hash_cache.update_cache(value)

    def report(self, previous=None):
        """
        Describe what has been replaced

        A dataset stores this so that the interface can say what was done to it
        rather than what was asked for. A count of zero means the field names
        were looked for but never found, and the data was left as it was.

        The same file can be gone over more than once, for instance to hash
        some fields and remove others. Pass what the dataset already records to
        add this run to it; leave it out when the file was written from scratch,
        as anything recorded earlier then describes data that is no longer there.

        A mode only counts once it has replaced something, so that a run which
        found none of its fields does not claim to have done anything. The
        patterns are kept either way, since they explain why nothing was found.

        :param dict previous:  An earlier report for the same file, if any
        :return dict:  The modes that replaced something, the field name
        patterns looked for, and how many values were replaced in total
        """
        previous = previous or {"modes": [], "fields": [], "replaced": 0}

        modes = set(previous["modes"])
        if self.replaced:
            modes.add(self.mode)

        return {
            "modes": sorted(modes),
            "fields": sorted({*previous["fields"], *self.fields}),
            "replaced": previous["replaced"] + self.replaced
        }

    def matching_names(self, names):
        """
        Find the field names that hold author information

        :param names:  Field names to check
        :return list:  The names matching one of this object's patterns
        """
        names = tuple(names)
        if names not in self._matches:
            # This guards against the possibility of different field names (e.g. via map_item)
            # names are lower cased before comparing, since the patterns are too
            self._matches[names] = [name for name in names if
                                    any(fnmatch.fnmatchcase(name.lower(), pattern) for pattern in self.fields)]

        return self._matches[names]

    def filter_row(self, row):
        """
        Replace author information in a flat row, e.g. a line of a CSV file

        The row is changed as it is, and also returned.

        :param dict row:  Row to replace values in
        :return dict:  The same row
        """
        for name in self.matching_names(row.keys()):
            row[name] = self.replace(row[name])

        return row

    def filter_item(self, item):
        """
        Replace author information in a nested item, e.g. a line of an NDJSON
        file

        When a matching name holds a list or an object, everything inside it is
        replaced as well.

        :param dict item:  Item to replace values in
        :return dict:  A copy of the item, with values replaced; the original
        is left alone
        """
        return dict_search_and_update(item, self.fields, self.replace)
