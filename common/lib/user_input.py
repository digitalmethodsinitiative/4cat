from dateutil.parser import parse as parse_datetime
from common.lib.exceptions import QueryParametersException

import re

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
    OPTION_DATE = "date"  # a single date
    OPTION_DATERANGE = "daterange"  # a beginning and end date
    OPTION_DIVIDER = "divider"  # meta-option, divides related sets of options
    OPTION_FILE = "file"  # file upload

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
        parsed_input = {}

        # all parameters are submitted as option-[parameter ID], this is an 
        # artifact of how the web interface works and we can simply remove the
        # prefix
        input = {re.sub(r"^option-", "", field): input[field] for field in input}

        for option, settings in options.items():
            if settings.get("type") in (UserInput.OPTION_DIVIDER, UserInput.OPTION_INFO):
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
                after, before = (UserInput.parse_value(settings, input.get(option_min), silently_correct), UserInput.parse_value(settings, input.get(option_max), silently_correct))

                if before and after and after > before:
                    if not silently_correct:
                        raise QueryParametersException("End of date range must be after beginning of date range.")
                    else:
                        before = after

                parsed_input[option] = (after, before)

            elif settings.get("type") == UserInput.OPTION_TOGGLE:
                # special case too, since if a checkbox is unchecked, it simply
                # does not show up in the input
                parsed_input[option] = option in input

            elif option not in input:
                # not provided? use default
                parsed_input[option] = settings.get("default", None)

            else:
                # normal parsing and sanitisation
                parsed_input[option] = UserInput.parse_value(settings, input[option], silently_correct)

        return parsed_input

    @staticmethod
    def parse_value(settings, choice, silently_correct=True):
        """
        Filter user input

        Makes sure user input for post-processors is valid and within the
        parameters specified by the post-processor

        :param obj settings:  Settings, including defaults and valid options
        :param choice:  The chosen option, to be parsed
        :param bool silently_correct:  If true, replace invalid values with the
        given default value; else, raise a QueryParametersException if a value
        is invalid.

        :return:  Validated and parsed input
        """
        input_type = settings.get("type", "")
        if input_type in (UserInput.OPTION_INFO, UserInput.OPTION_DIVIDER):
            # these are structural form elements and can never return a value
            return None

        elif input_type == UserInput.OPTION_TOGGLE:
            # simple boolean toggle
            return choice is not None

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

            chosen = choice.split(",")
            return [item for item in chosen if item in settings.get("options", [])]

        elif input_type == UserInput.OPTION_CHOICE:
            # select box
            # one out of multiple options
            # return option if valid, or default
            if choice not in settings.get("options"):
                if not silently_correct:
                    raise QueryParametersException("Invalid value selected; must be one of %s." % ", ".join(settings.get("options", {}).keys()))
                else:
                    return settings.get("default", "")
            else:
                return choice

        elif input_type in (UserInput.OPTION_TEXT, UserInput.OPTION_TEXT_LARGE):
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
