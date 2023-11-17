"""
Custom data upload to create bespoke datasets
"""
import secrets
import hashlib
import time
import csv
import re
import io

import datasources.upload.import_formats as import_formats

from dateutil.parser import parse as parse_datetime
from datetime import datetime

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import QueryParametersException, QueryNeedsFurtherInputException, \
    QueryNeedsExplicitConfirmationException
from common.lib.helpers import strip_tags, sniff_encoding, UserInput, HashCache


class SearchCustom(BasicProcessor):
    type = "upload-search"  # job ID
    category = "Search"  # category
    title = "Custom Dataset Upload"  # title displayed in UI
    description = "Upload your own CSV file to be used as a dataset"  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI
    is_local = False  # Whether this datasource is locally scraped
    is_static = False  # Whether this datasource is still updated

    max_workers = 1
    options = {
        "intro": {
            "type": UserInput.OPTION_INFO,
            "help": "You can upload a CSV or TAB file here that, after upload, will be available for further analysis "
                    "and processing. Files need to be [UTF-8](https://en.wikipedia.org/wiki/UTF-8)-encoded and must "
                    "contain a header row.\n\n"
                    "You can indicate what format the file has or upload one with arbitrary structure. In the latter "
                    "case, for each item, columns describing its ID, author, timestamp, and content are expected. You "
                    "can select which column holds which value after uploading the file."
        },
        "data_upload": {
            "type": UserInput.OPTION_FILE,
            "help": "File"
        },
        "format": {
            "type": UserInput.OPTION_CHOICE,
            "help": "CSV format",
            "options": {
                tool: info["name"] for tool, info in import_formats.tools.items()
            },
            "default": "custom"
        },
        "strip_html": {
            "type": UserInput.OPTION_TOGGLE,
            "help": "Strip HTML?",
            "default": False,
            "tooltip": "Removes HTML tags from the column identified as containing the item content ('body' by default)"
        }
    }

    def process(self):
        """
        Process uploaded CSV file

        Applies the provided mapping and makes sure the file is in a format
        4CAT will understand.
        """
        tool_format = import_formats.tools.get(self.parameters.get("format"))
        temp_file = self.dataset.get_results_path().with_suffix(".importing")
        with temp_file.open("rb") as infile:
            # detect encoding - UTF-8 with or without BOM
            encoding = sniff_encoding(infile)

        # figure out the csv dialect
        # the sniffer is not perfect and sometimes makes mistakes
        # for some formats we already know the dialect, so we can override its
        # guess and set the properties as defined in import_formats.py
        infile = temp_file.open("r", encoding=encoding)
        sample = infile.read(1024 * 1024)
        dialect = csv.Sniffer().sniff(sample, delimiters=(",", ";", "\t"))
        for prop in tool_format.get("csv_dialect", {}):
            setattr(dialect, prop, tool_format["csv_dialect"][prop])

        # With validated csvs, save as is but make sure the raw file is sorted
        infile.seek(0)
        reader = csv.DictReader(infile, dialect=dialect)

        if tool_format.get("columns") and not tool_format.get("allow_user_mapping") and set(reader.fieldnames) & \
                set(tool_format["columns"]) != set(tool_format["columns"]):
            raise QueryParametersException("Not all columns are present")

        # hasher for pseudonymisation
        salt = secrets.token_bytes(16)
        hasher = hashlib.blake2b(digest_size=24, salt=salt)
        hash_cache = HashCache(hasher)

        # write the resulting dataset
        writer = None
        done = 0
        skipped = 0
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline="") as output_csv:
            # mapper is defined in import_formats
            try:
                for item in tool_format["mapper"](reader, tool_format["columns"], self.dataset, self.parameters):
                    if isinstance(item, import_formats.InvalidImportedItem):
                        # if the mapper returns this class, the item is not written
                        skipped += 1
                        if hasattr(item, "reason"):
                            self.dataset.log(f"Skipping item ({item.reason})")
                        continue

                    if not writer:
                        writer = csv.DictWriter(output_csv, fieldnames=list(item.keys()))
                        writer.writeheader()

                    if self.parameters.get("strip_html") and "body" in item:
                        item["body"] = strip_tags(item["body"])

                    # pseudonymise or anonymise as needed
                    filtering = self.parameters.get("pseudonymise")
                    if filtering:
                        for field, value in item.items():
                            if field.startswith("author"):
                                if filtering == "anonymise":
                                    item[field] = "REDACTED"
                                elif filtering == "pseudonymise":
                                    item[field] = hash_cache.update_cache(value)

                    try:
                        writer.writerow(item)
                    except ValueError as e:
                        return self.dataset.finish_with_error("Could not parse CSV file. Have you selected the correct "
                                                              "format?")

                    done += 1

            except import_formats.InvalidCustomFormat as e:
                self.log.warning(f"Unable to import improperly formatted file for {tool_format['name']}. See dataset "
                                 "log for details.")
                infile.close()
                temp_file.unlink()
                return self.dataset.finish_with_error(str(e))

            except UnicodeDecodeError as e:
                infile.close()
                temp_file.unlink()
                return self.dataset.finish_with_error("The uploaded file is not encoded with the UTF-8 character set. "
                                                      "Make sure the file is encoded properly and try again.")

        # done!
        infile.close()
        if skipped:
            self.dataset.update_status(
                "CSV file imported, but %i items were skipped because their date could not be parsed." % skipped,
                is_final=True)

        temp_file.unlink()
        self.dataset.delete_parameter("filename")
        if skipped and not done:
            self.dataset.finish_with_error("No valid items could be found in the uploaded file. The column containing "
                                           "the item's timestamp may be in a format that cannot be parsed properly.")
        else:
            self.dataset.finish(done)

    def validate_query(query, request, user):
        """
        Validate custom data input

        Confirms that the uploaded file is a valid CSV or tab file and, if so, returns
        some metadata.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """
        # do we have an uploaded file?
        if "option-data_upload" not in request.files:
            raise QueryParametersException("No file was offered for upload.")

        file = request.files["option-data_upload"]
        if not file:
            raise QueryParametersException("No file was offered for upload.")

        if query.get("format") not in import_formats.tools:
            raise QueryParametersException("Cannot import CSV from tool %s" % str(query.get("format")))

        encoding = sniff_encoding(file)
        tool_format = import_formats.tools.get(query.get("format"))

        try:
            wrapped_file = io.TextIOWrapper(file, encoding=encoding)
            sample = wrapped_file.read(1024 * 1024)
            wrapped_file.seek(0)
            if not csv.Sniffer().has_header(sample) and not query.get("frontend-confirm"):
                raise QueryNeedsExplicitConfirmationException(
                    "The uploaded file does not seem to have a header row. Continue anyway?")
            dialect = csv.Sniffer().sniff(sample, delimiters=(",", ";", "\t"))

            # override the guesses for specific formats if defiend so in
            # import_formats.py
            for prop in tool_format.get("csv_dialect", {}):
                setattr(dialect, prop, tool_format["csv_dialect"][prop])
        except UnicodeDecodeError:
            raise QueryParametersException("The uploaded file does not seem to be a CSV file encoded with UTF-8. "
                                           "Save the file in the proper format and try again.")
        except csv.Error:
            raise QueryParametersException("Uploaded file is not a well-formed CSV or TAB file.")

        # With validated csvs, save as is but make sure the raw file is sorted
        reader = csv.DictReader(wrapped_file, dialect=dialect)

        # we know that the CSV file is a CSV file now, next verify whether
        # we know what each column means
        try:
            fields = reader.fieldnames
        except UnicodeDecodeError:
            raise QueryParametersException("Uploaded file is not a well-formed CSV or TAB file.")

        incomplete_mapping = list(tool_format["columns"])
        for field in tool_format["columns"]:
            if tool_format.get("allow_user_mapping", False) and "option-mapping-%s" % field in request.form:
                incomplete_mapping.remove(field)
            elif not tool_format.get("allow_user_mapping", False) and field in fields:
                incomplete_mapping.remove(field)

        # offer the user a number of select boxes where they can indicate the
        # mapping for each column
        column_mapping = {}
        if tool_format.get("allow_user_mapping", False):
            if incomplete_mapping:
                raise QueryNeedsFurtherInputException({
                    "mapping-info": {
                        "type": UserInput.OPTION_INFO,
                        "help": "Please confirm which column in the CSV file maps to each required value."
                    },
                    **{
                        "mapping-%s" % mappable_column: {
                            "type": UserInput.OPTION_CHOICE,
                            "options": {
                                "": "",
                                **({"__4cat_auto_sequence": "[generate sequential IDs]"} if mappable_column in (
                                "id", "thread_id") else {}),
                                **{column: column for column in fields}
                            },
                            "default": mappable_column if mappable_column in fields else "",
                            "help": mappable_column,
                            "tooltip": tool_format["columns"][mappable_column]
                        } for mappable_column in incomplete_mapping
                    }})

            # the mappings do need to point to a column in the csv file
            missing_mapping = []
            for field in tool_format["columns"]:
                mapping_field = "option-mapping-%s" % field
                provided_field = request.form.get(mapping_field)
                if (provided_field not in fields and provided_field != "__4cat_auto_sequence") or not provided_field:
                    missing_mapping.append(field)
                else:
                    column_mapping["mapping-" + field] = request.form.get(mapping_field)

            if missing_mapping:
                raise QueryParametersException(
                    "You need to indicate which column in the CSV file holds the corresponding value for the following "
                    "columns: %s" % ", ".join(missing_mapping))

        elif incomplete_mapping:
            raise QueryParametersException("The CSV file does not contain all required columns. The following columns "
                                           "are missing: %s" % ", ".join(incomplete_mapping))

        # the timestamp column needs to be parseable
        timestamp_column = request.form.get("mapping-timestamp")
        try:
            row = reader.__next__()
            if timestamp_column not in row:
                # incomplete row because we are analysing a sample
                # stop parsing because no complete rows will follow
                raise StopIteration

            try:
                if row[timestamp_column].isdecimal():
                    datetime.fromtimestamp(float(row[timestamp_column]))
                else:
                    parse_datetime(row[timestamp_column])
            except (ValueError, OSError):
                raise QueryParametersException(
                    "Your 'timestamp' column does not use a recognisable format (yyyy-mm-dd hh:mm:ss is recommended)")

        except StopIteration:
            pass

        # ok, we're done with the file
        wrapped_file.detach()

        # Whether to strip the HTML tags
        strip_html = False
        if query.get("strip_html"):
            strip_html = True

        # return metadata - the filename is sanitised and serves no purpose at
        # this point in time, but can be used to uniquely identify a dataset
        disallowed_characters = re.compile(r"[^a-zA-Z0-9._+-]")
        return {
            "filename": disallowed_characters.sub("", file.filename),
            "time": time.time(),
            "datasource": "upload",
            "board": query.get("format", "custom").replace("_", "-"),
            "format": query.get("format"),
            "strip_html": strip_html,
            **column_mapping,
        }

    def after_create(query, dataset, request):
        """
        Hook to execute after the dataset for this source has been created

        In this case, put the file in a temporary location so it can be
        processed properly by the related Job later.

        :param dict query:  Sanitised query parameters
        :param DataSet dataset:  Dataset created for this query
        :param request:  Flask request submitted for its creation
        """
        file = request.files["option-data_upload"]
        file.seek(0)
        with dataset.get_results_path().with_suffix(".importing").open("wb") as outfile:
            while True:
                chunk = file.read(1024)
                if len(chunk) == 0:
                    break
                outfile.write(chunk)
