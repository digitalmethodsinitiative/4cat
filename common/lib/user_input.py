from dateutil.parser import parse as parse_datetime
from common.lib.exceptions import QueryParametersException
from werkzeug.datastructures import ImmutableMultiDict
import json

import re

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
    OPTION_INFO = "info"  # just a bit of text, not actual input
    OPTION_TEXT_LARGE = "textarea"  # longer text
    OPTION_TEXT_JSON = "json"  # text, but should be valid JSON
    OPTION_DATE = "date"  # a single date
    OPTION_DATERANGE = "daterange"  # a beginning and end date
    OPTION_DIVIDER = "divider"  # meta-option, divides related sets of options
    OPTION_FILE = "file"  # file upload
    OPTION_HUE = "hue"  # colour hue
    OPTION_DATASOURCES = "datasources"  # data source toggling

    OPTIONS_COSMETIC = (OPTION_INFO, OPTION_DIVIDER)

    @staticmethod
    def parse_all(options, input, silently_correct=True):
        """
        Parse form input for the provided options

        Ignores all input not belonging to any of the defined options: parses
        and sanitises the rest, and returns a dictionary with the sanitised
        options. If an option is *not* present in the input, the default value
        is used, and if that is absent, `None`.

        In other words, this ensures a dictionary with 1) only white-listed
        keys, 2) a value of an expected type for each key.

        :param dict options:  Options, as a name -> settings dictionary
        :param dict input:  Input, as a form field -> value dictionary
        :param bool silently_correct:  If true, replace invalid values with the
        given default value; else, raise a QueryParametersException if a value
        is invalid.

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

            elif settings.get("type") == UserInput.OPTION_DATERANGE:
                # special case, since it combines two inputs
                option_min = option + "-min"
                option_max = option + "-max"

                # normally this is taken care of client-side, but in case this
                # didn't work, try to salvage it server-side
                if option_min not in input or input.get(option_min) == "-1":
                    option_min += "_proxy"

                if option_max not in input or input.get(option_max) == "-1":
                    option_max += "_proxy"

                # save as a tuple of unix timestamps (or None)
                try:
                    after, before = (UserInput.parse_value(settings, input.get(option_min), parsed_input, silently_correct), UserInput.parse_value(settings, input.get(option_max), parsed_input, silently_correct))

                    if before and after and after > before:
                        if not silently_correct:
                            raise QueryParametersException("End of date range must be after beginning of date range.")
                        else:
                            before = after

                    parsed_input[option] = (after, before)
                except RequirementsNotMetException:
                    pass

            elif settings.get("type") == UserInput.OPTION_TOGGLE:
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

            elif option not in input:
                # not provided? use default
                parsed_input[option] = settings.get("default", None)

            else:
                # normal parsing and sanitisation
                try:
                    parsed_input[option] = UserInput.parse_value(settings, input[option], parsed_input, silently_correct)
                except RequirementsNotMetException:
                    pass

        return parsed_input

    @staticmethod
    def parse_value(settings, choice, other_input=None, silently_correct=True):
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
        if settings.get("requires"):
            try:
                field, operator, value = re.findall(r"([a-zA-Z0-9_]+)([!=$~^]+)(.*)", settings.get("requires"))[0]
            except IndexError:
                # invalid condition, interpret as 'does the field with this name have a value'
                field, operator, value = (choice, "!=", "")

            if field not in other_input:
                raise RequirementsNotMetException()

            other_value = other_input.get(field)
            if type(other_value) is bool:
                # evalues to a boolean, i.e. checkboxes etc
                if operator == "!=":
                    if (other_value and value in ("", "false")) or (not other_value and value in ("true", "checked")):
                        raise RequirementsNotMetException()
                else:
                    if (other_value and value not in ("true", "checked")) or (not other_value and value not in ("", "false")):
                        raise RequirementsNotMetException()

            else:
                if type(other_value) in (tuple, list):
                # iterables are a bit special
                    if len(other_value) == 1:
                        # treat one-item lists as "normal" values
                        other_value = other_value[0]
                    elif operator == "~=":  # interpret as 'is in list?'
                        if value not in other_value:
                            raise RequirementsNotMetException()
                    else:
                        # condition doesn't make sense for a list, so assume it's not True
                        raise RequirementsNotMetException()

                if operator == "^=" and not str(other_value).startswith(value):
                    raise RequirementsNotMetException()
                elif operator == "$=" and not str(other_value).endswith(value):
                    raise RequirementsNotMetException()
                elif operator == "~=" and value not in str(other_value):
                    raise RequirementsNotMetException()
                elif operator == "!=" and value == other_value:
                    raise RequirementsNotMetException()
                elif operator in ("==", "=") and value != other_value:
                    raise RequirementsNotMetException()

        input_type = settings.get("type", "")
        if input_type in UserInput.OPTIONS_COSMETIC:
            # these are structural form elements and can never return a value
            return None

        elif input_type == UserInput.OPTION_TOGGLE:
            # simple boolean toggle
            if type(choice) == bool:
                return choice
            elif choice in ['false', 'False']:
                # Sanitized options passed back to Flask can be converted to strings as 'false'
                return False
            elif choice in ['true', 'True', 'on']:
                # Toggle will have value 'on', but may also becomes a string 'true'
                return True
            else:
                raise QueryParametersException("Toggle invalid input")

        elif input_type in (UserInput.OPTION_DATE, UserInput.OPTION_DATERANGE):
            # parse either integers (unix timestamps) or try to guess the date
            # format (the latter may be used for input if JavaScript is turned
            # off in the front-end and the input comes from there)
            value = None
            try:
                value = int(choice)
            except ValueError:
                parsed_choice = parse_datetime(choice)
                value = int(parsed_choice.timestamp())
            finally:
                return value

        elif input_type == UserInput.OPTION_MULTI:
            # any number of values out of a list of possible values
            # comma-separated during input, returned as a list of valid options
            if not choice:
                return settings.get("default", [])

            chosen = choice.split(",")
            return [item for item in chosen if item in settings.get("options", [])]

        elif input_type == UserInput.OPTION_MULTI_SELECT:
            # multiple number of values out of a dropdown list of possible values
            # comma-separated during input, returned as a list of valid options
            if not choice:
                return settings.get("default", [])

            if type(choice) is str:
                # should be a list if the form control was actually a multiselect
                # but we have some client side UI helpers that may produce a string
                # instead
                choice = choice.split(",")

            return [item for item in choice if item in settings.get("options", [])]

        elif input_type == UserInput.OPTION_CHOICE:
            # select box
            # one out of multiple options
            # return option if valid, or default
            if choice not in settings.get("options"):
                if not silently_correct:
                    raise QueryParametersException(f"Invalid value selected; must be one of {', '.join(settings.get('options', {}).keys())}. {settings}")
                else:
                    return settings.get("default", "")
            else:
                return choice

        elif input_type == UserInput.OPTION_TEXT_JSON:
            # verify that this is actually json
            try:
                redumped_value = json.dumps(json.loads(choice))
            except json.JSONDecodeError:
                raise QueryParametersException("Invalid JSON value '%s'" % choice)

            return json.loads(choice)

        elif input_type in (UserInput.OPTION_TEXT, UserInput.OPTION_TEXT_LARGE, UserInput.OPTION_HUE):
            # text string
            # optionally clamp it as an integer; return default if not a valid
            # integer (or float; inferred from default or made explicit via the
            # coerce_type setting)
            if settings.get("coerce_type"):
                value_type = settings["coerce_type"]
            else:
                value_type = type(settings.get("default"))
                if value_type not in (int, float):
                    value_type = int

            if "max" in settings:
                try:
                    choice = min(settings["max"], value_type(choice))
                except (ValueError, TypeError) as e:
                    if not silently_correct:
                        raise QueryParametersException("Provide a value of %s or lower." % str(settings["max"]))

                    choice = settings.get("default")

            if "min" in settings:
                try:
                    choice = max(settings["min"], value_type(choice))
                except (ValueError, TypeError) as e:
                    if not silently_correct:
                        raise QueryParametersException("Provide a value of %s or more." % str(settings["min"]))

                    choice = settings.get("default")

            if choice is None or choice == "":
                choice = settings.get("default")

            if choice is None:
                choice = 0 if "min" in settings or "max" in settings else ""

            if settings.get("coerce_type"):
                try:
                    return value_type(choice)
                except (ValueError, TypeError):
                    return settings.get("default")
            else:
                return choice

        else:
            # no filtering
            return choice
