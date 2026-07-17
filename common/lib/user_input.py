from dateutil.parser import parse as parse_datetime
from common.lib.exceptions import QueryParametersException
from werkzeug.datastructures import ImmutableMultiDict
import json

import re
from itertools import chain

class RequirementsNotMetException(Exception):
    """
    If this is raised while parsing, that option is not included in the parsed
    output. Used with the "requires" option setting.
    """
    pass

class UserInput:
    """
    Class for handling user input

    It is important to sanitise user input, as carelessly entered parameters
    may in e.g. requesting far more data than needed, or lead to undefined
    behaviour. This class offers a set of pre-defined value types that can be
    consistently rendered as form elements in an interface and parsed.
    """
    OPTION_TOGGLE = "toggle"  # boolean toggle (checkbox)
    OPTION_CHOICE = "choice"  # one choice out of a list (select)
    OPTION_TEXT = "string"  # simple string or integer (input text)
    OPTION_MULTI = "multi"  # multiple values out of a list (select multiple)
    OPTION_MULTI_SELECT = "multi_select"  # multiple values out of a dropdown list (select multiple)
    OPTION_MULTI_OPTION = "multi_option"  # several instances of a collection of controls
    OPTION_INFO = "info"  # just a bit of text, not actual input
    OPTION_TEXT_LARGE = "textarea"  # longer text
    OPTION_TEXT_JSON = "json"  # text, but should be valid JSON
    OPTION_DATERANGE = "daterange"  # a beginning and end date
    OPTION_DIVIDER = "divider"  # meta-option, divides related sets of options
    OPTION_FILE = "file"  # file upload
    OPTION_HUE = "hue"  # colour hue
    OPTION_DATASOURCES = "datasources"  # data source toggling
    OPTION_EXTENSIONS = "extensions"  # extension toggling
    OPTION_DATASOURCES_TABLE = "datasources_table"  # a table with settings per data source
    OPTION_ANNOTATION = "annotation"  # checkbox for whether to an annotation
    OPTION_ANNOTATIONS = "annotations"  # table for whether to write multiple annotations

    OPTIONS_COSMETIC = (OPTION_INFO, OPTION_DIVIDER)

    # the keys the framework understands in an option's settings dict. a key
    # outside this set is almost always a typo (e.g. "coerce" for
    # "coerce_type"), which is silently ignored and so has no effect - the
    # module test flags these so they are caught rather than shipped.
    KNOWN_OPTION_KEYS = frozenset({
        # -- read by the parser / module loader --
        "type",          # UI/control type of the option (toggle, choice, string, ...)
        "default",       # value used when the option is not present in submitted input
        "options",       # valid choices for choice/multi/annotation options
        "requires",      # condition(s) controlling when the option is shown/parsed
        "min",           # minimum allowed value for numeric text options
        "max",           # maximum allowed value for numeric text options
        "coerce_type",   # Python type (int, float) the parsed value is coerced to
        "indirect",      # derived from other settings; skipped during parsing
        "delegated",     # shown/parsed only when dynamically delegated by another option
        "dict_key",      # sub-field or callable used as key for multi_option items
        "columns",       # sub-option definitions for table-style options
        "sensitive",     # treated as sensitive; excluded from public displays/logs and deleted on run
        "mandatory",     # user-submitted value must not be blank/empty

        # -- read by the interface templates --
        "help",            # primary label/help text shown next to the form control
        "tooltip",         # longer explanatory text shown as tooltip or placeholder
        "label",           # display label for annotation badges
        "inline",          # render multi/multi_select choices inline
        "original_default",  # configured default preserved when the live value is overridden (settings panel)
        "value",           # HSV lightness/value component for hue colour pickers
        "saturation",      # HSV saturation component for hue colour pickers
        "accept",          # accepted file type for file inputs
        "update",          # CSS selector to update with hue picker changes
        "password",        # render string input as a password field
        "multiple",        # allow selecting multiple files
        "cache",           # tell the frontend to cache the value locally

        # -- annotation options --
        "to_parent",          # attach annotations to the parent dataset
        "hide_in_explorer",   # hide annotation column from the Explorer UI

        # -- datasource options --
        "board_specific",   # list of board IDs for which the option is shown

        # -- config/admin settings --
        "global",   # setting applies across all users (not user-scoped)
    })

    @staticmethod
    def unknown_option_keys(settings):
        """
        List an option's settings keys that the framework does not understand

        Unknown keys are silently ignored at parse time, so a typo like
        "coerce" (for "coerce_type") quietly does nothing. Used by the module
        test to catch these.

        :param dict settings:  An option's settings dictionary
        :return list:  The unrecognised keys, sorted (empty if all are known)
        """
        if not isinstance(settings, dict):
            return []
        return sorted(set(settings) - UserInput.KNOWN_OPTION_KEYS)

    @staticmethod
    def parse_all(options, input, silently_correct=False, log=None):
        """
        Parse form input for the provided options

        Ignores all input not belonging to any of the defined options: parses
        and sanitises the rest, and returns a dictionary with the sanitised
        options.

        An option that is *not* present in the input at all is an error when
        parsing strictly: our own form always submits every field it shows, so
        a missing option means an incomplete submission (e.g. an API call that
        left it out), and quietly proceeding without it would let later checks
        pass on values the caller never sent. Exceptions are options a form
        legitimately leaves out: unchecked toggles (submitted as nothing, read
        as False), file uploads (sent outside the form values), fields gated
        by an unmet "requires" condition or by "board_specific" (left out of
        the result), and unticked multi-selects (the form submits an empty
        marker so they are still present). When parsing tolerantly
        (silently_correct), a missing option gets its default instead.

        In other words, this ensures a dictionary with 1) only white-listed
        keys, 2) a value of an expected type for each key, and 3) when strict,
        a complete submission.

        :param dict options:  Options, as a name -> settings dictionary
        :param dict input:  Input, as a form field -> value dictionary
        :param bool silently_correct:  If true, replace invalid values with the
        given default value; else, raise a QueryParametersException if a value
        is invalid. Defaults to false: every real caller wants the strict
        behaviour, and tolerant parsing should be opted into deliberately.
        :param log:  Optional logger. When an option's *default* value turns
        out to be invalid (a developer mistake, not user input), a warning is
        logged here and the default is corrected silently rather than shown to
        the user.

        :return dict:  Sanitised form input
        """

        from common.lib.helpers import convert_to_int
        parsed_input = {}

        if type(input) is not dict and type(input) is not ImmutableMultiDict:
            raise TypeError("input must be a dictionary or ImmutableMultiDict")

        if type(input) is ImmutableMultiDict:
            # we are not using to_dict, because that messes up multi-selects
            input = {key: input.getlist(key) for key in input}
            for key, value in input.items():
                if type(value) is list and len(value) == 1:
                    input[key] = value[0]

        # all parameters are submitted as option-[parameter ID], this is an 
        # artifact of how the web interface works and we can simply remove the
        # prefix
        input = {re.sub(r"^option-", "", field): input[field] for field in input}

        # fields can be 'delegated', i.e. they only show up under some condition
        # or in a later stage of form input. here we determine if input was
        # actually filled in or was only defined but never delegated
        never_delegated = set([option for option in options if options[option].get("delegated")])
        never_delegated -= set(input.keys())

        # re-order input so that the fields relying on the value of other
        # fields are parsed last
        options = {k: options[k] for k in sorted(options, key=lambda k: options[k].get("requires") is not None)}

        for option, settings in options.items():
            if settings.get("indirect"):
                # these are settings that are derived from and set by other
                # settings
                continue

            if settings.get("type") in UserInput.OPTIONS_COSMETIC:
                # these are structural form elements and never have a value
                continue

            if option in never_delegated:
                # these options were never actually part of the input because
                # the required conditions were never met, so they can be
                # ignored
                continue

            if settings.get("requires") and not UserInput.requirements_met(settings["requires"], parsed_input):
                # the option's condition is not met, so the user never saw it:
                # leave it out instead of storing a default for it. This holds
                # whether or not the (hidden) form field was submitted.
                continue

            # an option's default is set by us, not by the user, so an invalid
            # one is a bug in the option definition: warn developers about it.
            # it is deliberately not corrected quietly. the form pre-fills
            # defaults, so a bad default comes back looking like a value the
            # user typed; silently replacing it would run the analysis on a
            # value the user never chose and cannot see, which is worse than an
            # error. it is validated like any other value below, so it gets
            # reported (naming the option) rather than hidden.
            default_problem = UserInput.validate_default(settings)
            if default_problem and log:
                log.warning("Option '%s' has an invalid default (%s). "
                            "Please fix the option definition." % (option, default_problem))

            if settings.get("type") == UserInput.OPTION_DATERANGE:
                # special case, since it combines two inputs
                option_min = option + "-min"
                option_max = option + "-max"

                # normally this is taken care of client-side, but in case this
                # didn't work, try to salvage it server-side
                if option_min not in input or input.get(option_min) == "-1":
                    option_min += "_proxy"

                if option_max not in input or input.get(option_max) == "-1":
                    option_max += "_proxy"

                if settings.get("mandatory") and UserInput.is_empty_value(input.get(option_min)) and UserInput.is_empty_value(input.get(option_max)):
                    raise QueryParametersException("%s: This field is required." % (settings.get("help") or option))

                # save as a tuple of unix timestamps (or None)
                try:
                    after, before = (UserInput.parse_value(settings, input.get(option_min), parsed_input, silently_correct), UserInput.parse_value(settings, input.get(option_max), parsed_input, silently_correct))

                    if before and after and after > before:
                        if not silently_correct:
                            raise QueryParametersException("the start of the date range must be before its end.")
                        else:
                            before = after

                    parsed_input[option] = (after, before)
                except RequirementsNotMetException:
                    pass
                except QueryParametersException as e:
                    # say which option the problem is about; parse_value only
                    # sees an option's settings, not its name
                    raise QueryParametersException("%s: %s" % (settings.get("help") or option, e))

            elif settings.get("type") in (UserInput.OPTION_TOGGLE, UserInput.OPTION_ANNOTATION):
                # special case too, since if a checkbox is unchecked, it simply
                # does not show up in the input
                try:
                    if option in input:
                        # Toggle needs to be parsed
                        parsed_input[option] = UserInput.parse_value(settings, input[option], parsed_input, silently_correct)
                    else:
                        # Toggle was left blank
                        parsed_input[option] = False
                except RequirementsNotMetException:
                    pass
                except QueryParametersException as e:
                    raise QueryParametersException("%s: %s" % (settings.get("help") or option, e))

            elif settings.get("type") == UserInput.OPTION_DATASOURCES:
                # special case, because this combines multiple inputs to
                # configure data source availability and expiration
                datasources = {datasource: {
                    "enabled": f"{option}-enable-{datasource}" in input,
                    "allow_optout": f"{option}-optout-{datasource}" in input,
                    "timeout": convert_to_int(input[f"{option}-timeout-{datasource}"], 0)
                } for datasource in input[option].split(",")}

                parsed_input[option] = [datasource for datasource, v in datasources.items() if v["enabled"]]
                parsed_input[option.split(".")[0] + ".expiration"] = datasources

            elif settings.get("type") == UserInput.OPTION_EXTENSIONS:
                # also a special case
                parsed_input[option] = {extension: {
                    "enabled": f"{option}-enable-{extension}" in input
                } for extension in input[option].split(",")}

            elif settings.get("type") == UserInput.OPTION_DATASOURCES_TABLE:
                # special case, parse table values to generate a dict
                columns = list(settings["columns"].keys())
                table_input = {}

                for datasource in list(settings["default"].keys()):
                    table_input[datasource] = {}
                    for column in columns:

                        choice = input.get(option + "-" + datasource + "-" + column, False)
                        column_settings = settings["columns"][column]  # sub-settings per column
                        table_input[datasource][column] = UserInput.parse_value(column_settings, choice, table_input, silently_correct=silently_correct)

                parsed_input[option] = table_input

            elif settings.get("type") == UserInput.OPTION_MULTI_OPTION:
                # these are collections of other input options that can be
                # repeated an arbitrary amount of times and are saved as a
                # list of these values
                # i.e. forms within forms!!!
                item_options = settings["options"]
                input_items = {}

                if settings.get("mandatory") and not any(re.match(f"{option}-([0-9]+)-(.+)", key) for key in input):
                    raise QueryParametersException("%s: This field is required." % (settings.get("help") or option))

                for key, value in input.items():
                    if key_match := re.match(f"{option}-([0-9]+)-(.+)", key):
                        input_index = int(key_match[1])
                        # note: the index is just used to match inputs to items
                        # it is not used for ordering
                        option_item = key_match[2]
                        if option_item not in item_options:
                            continue

                        if input_index not in input_items:
                            input_items[input_index] = {}

                        input_items[input_index][option_item] = UserInput.parse_value(item_options[option_item], value, input_items[input_index], silently_correct)

                # discard items that are only default values
                parsed_input[option] = []
                for input_index, item in input_items.items():
                    only_default = True
                    for key, value in item.items():
                        if value != item_options[key]["default"]:
                            only_default = False

                    if not only_default:
                        parsed_input[option].append(item)

                # may define a mapper to make this a dict
                if settings.get("dict_key"):
                    if callable(settings["dict_key"]):
                        parsed_input[option] = {settings["dict_key"](value): {**value, "_id": settings["dict_key"](value)} for value in parsed_input[option]}
                    else:
                        parsed_input[option] = {value[settings["dict_key"]]: {**value, "_id": value[settings["dict_key"]]} for value in parsed_input[option]}

            elif option not in input:
                # the option was not part of the submission at all. our own
                # form always submits every field it shows - fields hidden by
                # an unmet "requires" condition were already dropped above -
                # so apart from the two exceptions below, a missing option
                # means an incomplete submission.
                if settings.get("type") == UserInput.OPTION_FILE:
                    # a file input's content does not travel among the form
                    # values (it is sent separately, in request.files), so it
                    # is never present here; whether a file was actually
                    # uploaded is for the module's validate_query to check
                    pass

                elif settings.get("board_specific"):
                    # only shown for particular boards: the form disables the
                    # field when another board is selected, and a disabled
                    # field is not submitted. like an unmet "requires", the
                    # user never saw it, so leave it out
                    pass

                elif settings.get("mandatory"):
                    raise QueryParametersException("%s: This field is required." % (settings.get("help") or option))

                elif silently_correct:
                    # a caller that asked to be corrected quietly gets the
                    # default filled in
                    parsed_input[option] = settings.get("default", None)

                else:
                    # strict parsing: quietly filling in the default - or
                    # quietly leaving the option out - would let later checks
                    # pass on a value the caller never sent. an incomplete
                    # submission is the caller's mistake, so say so.
                    raise QueryParametersException(
                        "%s: this field was missing from the submitted form." % (settings.get("help") or option))

            else:
                # normal parsing and sanitisation
                try:
                    if settings.get("mandatory") and UserInput.is_empty_value(input[option]):
                        raise QueryParametersException("This field is required.")

                    parsed_input[option] = UserInput.parse_value(settings, input[option], parsed_input, silently_correct)
                except RequirementsNotMetException:
                    pass
                except QueryParametersException as e:
                    # say which option the problem is about; parse_value only
                    # sees an option's settings, not its name
                    raise QueryParametersException("%s: %s" % (settings.get("help") or option, e))

        return parsed_input

    @staticmethod
    def is_empty_value(value):
        """
        Check whether a raw submitted value counts as blank for mandatory fields

        None, empty strings, and empty lists are treated as blank. Whitespace-
        only strings are also considered blank. This is intentionally lenient
        for other types; parse_value handles detailed validation.

        :param value:  Raw submitted value
        :return bool:  True if the value is blank
        """
        if value is None:
            return True
        if isinstance(value, str) and value.strip() == "":
            return True
        if isinstance(value, list) and len(value) == 0:
            return True
        return False

    @staticmethod
    def requirements_met(requires, other_input):
        """
        Check whether an option's "requires" condition is satisfied

        `requires` may be:
          - a single string:          "field==value"
          - an &&-joined string:      "field1==v1 && field2==v2"  (all must be true)
          - a ||-joined string:       "field1==v1 || field2==v2"  (any must be true)
          - a list/tuple of strings:  every requirement must be true

        :param requires:  The option's "requires" setting
        :param dict other_input:  Values to check the condition against; a
          condition that refers to a field missing from this dictionary is
          not met
        :return bool:  True if the condition is satisfied
        """
        if isinstance(requires, (list, tuple)):
            # a list always means: every requirement must be satisfied
            req_list = list(requires)
            combine_and = True
        elif "||" in requires:
            # pipe-separated alternatives: any one is sufficient
            req_list = [r.strip() for r in requires.split("||")]
            combine_and = False
        elif "&&" in requires:
            # ampersand-separated conditions: all must hold
            req_list = [r.strip() for r in requires.split("&&")]
            combine_and = True
        else:
            # single requirement string
            req_list = [requires]
            combine_and = True

        results = [UserInput._requirement_met(r, other_input) for r in req_list]
        return all(results) if combine_and else any(results)

    @staticmethod
    def _requirement_met(req, other_input):
        """
        Evaluate a single requirement expression against already-parsed input.

        A requirement is a string of the form ``field[operator]value``. Returns
        True if the requirement is satisfied, False otherwise. The caller is
        responsible for combining the results of multiple requirements with the
        appropriate AND/OR logic.

        Supported operators:
          ==  / =   exact equality
          !=        negated equality
          ^=        value starts with
          !^=       value does not start with
          $=        value ends with
          !$=       value does not end with
          ~=        value contains (or, for lists, is a member of)
          !~=       value does not contain / is not a member of

        :param str req:          The requirement string to evaluate.
        :param dict other_input: Already-parsed input to check against.
        :return bool:            True if the requirement is satisfied.
        """
        try:
            field, operator, value = re.findall(r"([a-zA-Z0-9_-]+)([!=$~^]+)(.*)", req)[0]
        except IndexError:
            # no operator found: treat the whole string as a bare field name
            # and check that a field with that name is present and non-empty
            field, operator, value = (req, "!=", "")

        if not other_input or field not in other_input:
            # the referenced field has not been parsed yet (or no input at all)
            return False

        negated = operator.startswith("!")
        if negated:
            operator = operator[1:]

        other_value = other_input.get(field)
        if type(other_value) is bool:
            # boolean values come from toggle/checkbox options
            if operator in ("==", "="):
                # True matches "true"/"checked"; False matches ""/"false"
                if ((other_value and value in ("", "false")) or (not other_value and value in ("true", "checked"))) != negated:
                    return False
            else:
                # any non-equality operator: check truthy/falsy in the same way
                if ((other_value and value not in ("true", "checked")) or (not other_value and value not in ("", "false"))) != negated:
                    return False

        else:
            if type(other_value) in (tuple, list):
                # iterables are a bit special
                if len(other_value) == 1:
                    # single-item list: unwrap and treat as a scalar below
                    other_value = other_value[0]
                elif operator == "~=":
                    # multi-item list + ~= means 'is value a member of this list?'
                    if (value not in other_value) != negated:
                        return False
                    return True  # handled; skip scalar checks below
                elif not negated:
                    # other operators don't have a meaningful multi-item list
                    # interpretation; treat as not satisfied
                    return False
                # a negated non-~= operator on a multi-item list falls through
                # to the scalar checks below (with other_value still a list)

            # scalar (or unwrapped single-item list) comparisons
            if operator == "^=" and str(other_value).startswith(value) == negated:
                # starts-with check
                return False
            elif operator == "$=" and str(other_value).endswith(value) == negated:
                # ends-with check
                return False
            elif operator == "~=" and (value in str(other_value)) == negated:
                # substring / contains check
                return False
            elif operator in ("==", "=") and (value == other_value) == negated:
                # exact-equality check
                return False

        return True

    @staticmethod
    def parse_value(settings, choice, other_input=None, silently_correct=False):
        """
        Filter user input

        Makes sure user input for post-processors is valid and within the
        parameters specified by the post-processor

        :param obj settings:  Settings, including defaults and valid options
        :param choice:  The chosen option, to be parsed
        :param dict other_input:  Other input, as parsed so far
        :param bool silently_correct:  If true, replace invalid values with the
        given default value; else, raise a QueryParametersException if a value
        is invalid.

        :return:  Validated and parsed input
        """
        # short-circuit if there is a requirement for the field to be parsed
        # and the requirement isn't met
        if settings.get("requires") and not UserInput.requirements_met(settings["requires"], other_input):
            raise RequirementsNotMetException()

        input_type = settings.get("type", "")
        if input_type in UserInput.OPTIONS_COSMETIC:
            # these are structural form elements and can never return a value
            return None

        elif input_type in (UserInput.OPTION_TOGGLE, UserInput.OPTION_ANNOTATION):
            # simple boolean toggle
            if type(choice) is bool:
                return choice
            elif choice in ['false', 'False']:
                # Sanitized options passed back to Flask can be converted to strings as 'false'
                return False
            elif choice in ['true', 'True', 'on']:
                # Toggle will have value 'on', but may also becomes a string 'true'
                return True
            else:
                raise QueryParametersException("Toggle invalid input")

        elif input_type == UserInput.OPTION_DATERANGE:
            # parse either integers (unix timestamps) or try to guess the date
            # format (the latter may be used for input if JavaScript is turned
            # off in the front-end and the input comes from there)
            if choice is None or choice == "":
                # this end of the range was left empty
                return None
            try:
                return int(choice)
            except (ValueError, TypeError):
                pass
            try:
                return int(parse_datetime(choice).timestamp())
            except (ValueError, TypeError, OverflowError):
                # not a number and not a date we can recognise. (previously this
                # was swallowed by a return inside a finally block and silently
                # became an open-ended range.)
                if not silently_correct:
                    raise QueryParametersException("'%s' is not a valid date." % choice)
                return None

        elif input_type in (UserInput.OPTION_MULTI, UserInput.OPTION_ANNOTATIONS, UserInput.OPTION_MULTI_SELECT):
            # any number of values out of a list of possible values. these
            # arrive either comma-separated (text controls and some client-side
            # helpers) or as an actual list (real multi-selects and raw API
            # callers), so accept both shapes. (OPTION_MULTI used to assume a
            # string and crashed on a real list.)
            if type(choice) is str:
                choice = choice.split(",")

            # the form submits an empty value alongside whatever is selected, so
            # that the field is present even when nothing is: a browser leaves a
            # select with no selection out of the submission entirely, which is
            # indistinguishable from the field never having been shown. discard
            # that empty marker, and treat what remains as the selection.
            choice = [item for item in (choice or []) if item != ""]

            if not choice:
                if settings.get("mandatory"):
                    raise QueryParametersException("This field is required.")
                if silently_correct:
                    return settings.get("default", [])
                # a submitted-but-empty selection means the user unticked
                # everything: a choice of nothing, not a request for the
                # default back
                return []

            options = settings.get("options", [])
            invalid = [item for item in choice if item not in options]
            if invalid and not silently_correct:
                raise QueryParametersException("Invalid value(s) selected: %s." % ", ".join(str(i) for i in invalid))

            return [item for item in choice if item in options]

        elif input_type == UserInput.OPTION_CHOICE:
            # select box
            # one out of multiple options
            # return option if valid, or default
            options = settings.get("options", {})

            # if we have a categorised set of options, look deeper to get
            # valid option values
            is_categorised = all([type(o) is dict for o in options.values()])
            match_options = list(chain(*[list(o.keys()) for o in options.values()])) if is_categorised else options

            if choice not in match_options:
                if not silently_correct:
                    raise QueryParametersException(f"Invalid value selected; must be one of {', '.join(match_options)}.")
                else:
                    return settings.get("default", "")
            else:
                return choice

        elif input_type == UserInput.OPTION_TEXT_JSON:
            # verify that this is actually json
            try:
                json.dumps(json.loads(choice))
            except json.JSONDecodeError:
                raise QueryParametersException("Invalid JSON value '%s'" % choice)

            return json.loads(choice)

        elif input_type in (UserInput.OPTION_TEXT, UserInput.OPTION_TEXT_LARGE, UserInput.OPTION_HUE):
            # a text field. it may be a plain string, or constrained to a number
            # by a coerce_type (e.g. int) and/or a min/max. for a numeric field,
            # a non-number or an out-of-range value is rejected (when
            # silently_correct is off) or corrected to the default / nearest
            # bound (when it is on).
            coerce_type = settings.get("coerce_type")
            if coerce_type is not None and not callable(coerce_type):
                # the option is declared wrong: coerce_type should be a type
                # such as int or float, not e.g. the string "int"
                if not silently_correct:
                    raise QueryParametersException("This option is misconfigured: its coerce_type is not a type.")
                coerce_type = None

            has_range = "min" in settings or "max" in settings
            if coerce_type in (int, float):
                number_type = coerce_type
            elif has_range:
                default_type = type(settings.get("default"))
                number_type = default_type if default_type in (int, float) else int
            else:
                number_type = None

            if choice is None or choice == "":
                # an empty value that was actively submitted - an option left
                # out of the submission never reaches this point. the default
                # is not quietly filled back in: the form showed it, and the
                # user removed it. for a text field, empty is an answer
                # ("nothing"); for a numeric field it is not one. a tolerant
                # caller gets the correcting behaviour, i.e. the default.
                if silently_correct:
                    choice = settings.get("default")
                    if choice is None:
                        choice = 0 if number_type is not None else ""
                elif number_type is None:
                    return ""
                else:
                    raise QueryParametersException("This field needs a number.")

            elif number_type is not None:
                # a number is expected: coerce it first, then keep it in range.
                # coercion and range are checked separately so the error
                # actually matches the problem (a non-number no longer reports
                # an out-of-range message, and an out-of-range value is no
                # longer silently clamped away).
                try:
                    choice = number_type(choice)
                except (ValueError, TypeError):
                    if not silently_correct:
                        raise QueryParametersException("'%s' is not a valid number." % choice)
                    choice = settings.get("default")
                else:
                    if "max" in settings and choice > settings["max"]:
                        if not silently_correct:
                            raise QueryParametersException("Provide a value of %s or lower." % str(settings["max"]))
                        choice = settings["max"]
                    if "min" in settings and choice < settings["min"]:
                        if not silently_correct:
                            raise QueryParametersException("Provide a value of %s or more." % str(settings["min"]))
                        choice = settings["min"]

            # apply an explicit coerce_type so a value that came from the default
            # still has the declared type
            if coerce_type:
                try:
                    return coerce_type(choice)
                except (ValueError, TypeError):
                    if not silently_correct:
                        raise QueryParametersException("This option's default value cannot be parsed.")
                    return settings.get("default")

            return choice

        else:
            # no filtering
            return choice

    @staticmethod
    def validate_default(settings):
        """
        Check an option's own default value against the option's own rules

        A default is set by the developer, so a bad one is a bug in the option
        definition, not something a user should ever see. This is what the
        module test uses to catch those bugs, and what `parse_all` uses at
        runtime to correct them quietly (see there).

        The value rules live in one place, `parse_value`: for the types where it
        applies, this feeds the default back through `parse_value` (strictly,
        and ignoring any "requires" gate, since we are checking the value on its
        own) and reports whatever it rejects. Only a few structural checks that
        `parse_value` cannot express are done here directly.

        Membership of a choice or multi-choice default in its option list is
        checked only when that list is populated. Such lists are often built
        from the parent dataset, so at test time (with no real parent) they may
        be empty, in which case the check is skipped; at runtime the list is
        authoritative and the check catches a default that isn't a real option.

        :param dict settings:  An option's settings dictionary
        :return str|None:  A short developer-facing description of the problem,
          or None if the default is fine
        """
        default = settings.get("default")
        input_type = settings.get("type")

        # an empty or absent default means "no default; the user must choose",
        # which is a legitimate pattern rather than a mistake
        if default is None or default == "" or default == [] or default == {}:
            return None

        if input_type in (UserInput.OPTION_MULTI, UserInput.OPTION_MULTI_SELECT, UserInput.OPTION_ANNOTATIONS):
            # a multi-value default must be a list; a bare string or, worse, a
            # generator leaks a wrong-typed value into stored parameters
            if not isinstance(default, list):
                return "default should be a list, not %s" % type(default).__name__

        # for choice/multi options, membership can only be checked when the
        # list of options is populated (see docstring); skip it otherwise
        if input_type in (UserInput.OPTION_CHOICE, UserInput.OPTION_MULTI,
                          UserInput.OPTION_MULTI_SELECT, UserInput.OPTION_ANNOTATIONS) and not settings.get("options"):
            return None

        if input_type == UserInput.OPTION_TEXT_JSON:
            # a JSON option's default is a Python object, not a raw string, so
            # check it is serialisable instead of sending it through parse_value
            try:
                json.dumps(default)
                return None
            except (TypeError, ValueError) as e:
                return "default is not valid JSON (%s)" % e

        if input_type == UserInput.OPTION_DATERANGE:
            # date ranges have no meaningful single default value
            return None

        probe = {key: value for key, value in settings.items() if key != "requires"}
        try:
            UserInput.parse_value(probe, default, silently_correct=False)
            return None
        except QueryParametersException as e:
            return str(e)
        except RequirementsNotMetException:
            return None
