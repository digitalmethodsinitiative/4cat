"""
Classify text content with large language models
"""
import shutil
import json
import csv
import re
import io

from backend.lib.processor import BasicProcessor
from common.lib.dmi_service_manager import DmiServiceManager, DmiServiceManagerException, DsmOutOfMemory
from common.lib.exceptions import QueryParametersException
from common.lib.user_input import UserInput
from common.lib.helpers import sniff_encoding, sniff_csv_dialect
from common.config_manager import config

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class TextClassifier(BasicProcessor):
    """
    Classify text using a large language model of choice
    """
    type = "text-classification-llm"  # job type ID
    category = "Text analysis"  # category
    title = "Classify text using large language models"  # title displayed in UI
    description = ("Given a list of categories, use a large language model to classify text content into one of the "
                   "provided categories.")  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    references = [
        "Annotations are made using the [Stormtrooper](https://centre-for-humanities-computing.github.io/stormtrooper/) library",
        "Model card: [google/flan-t5-large](https://huggingface.co/google/flan-t5-large)",
        "Model card: [tiiuae/falcon-7b-instruct](https://huggingface.co/tiiuae/falcon-7b-instruct)",
        "Model card: [meta-llama/Meta-Llama-3.1-8B-Instruct](https://huggingface.co/meta-llama/Meta-Llama-3.1-8B-Instruct)"
    ]

    config = {
        "dmi-service-manager.stormtrooper_intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "Text classification",
        },
        "dmi-service-manager.stormtrooper_enabled": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Enable LLM-powered text classification",
        },
        "dmi-service-manager.stormtrooper_models": {
            "type": UserInput.OPTION_TEXT,
            "default": "google/flan-t5-large,tiiaue/falcon-7b-instruct",
            "help": "Comma-separated list of models that can be selected"
        }
    }

    options = {
        "text-column": {
            "type": UserInput.OPTION_TEXT,
            "default": False,
            "help": "Data field to classify"
        },
        "model": {
            "type": UserInput.OPTION_CHOICE,
            "default": "google/flan-t5-large",
            "options": {
            },
            "help": "Large Language Model to use"
        },
        "shotstyle": {
            "type": UserInput.OPTION_CHOICE,
            "help": "Classification style",
            "options": {
                "zeroshot": "Zero-shot classification (just categories, no examples)",
                "fewshot": "Few-shot classification (provide a few examples per category)"
            },
            "default": "zeroshot"
        },
        "categories": {
            "type": UserInput.OPTION_TEXT,
            "default": "",
            "help": "Categories",
            "tooltip": "Categories to choose from. Separate with commas.",
            "requires": "shotstyle==zeroshot"
        },
        "category-file": {
            "type": UserInput.OPTION_FILE,
            "help": "Labels (CSV file)",
            "tooltip": "CSV file containing two columns; one with the label, and a second one with an example for the "
                       "label. There can be multiple rows per label, with different examples each.",
            "requires": "shotstyle==fewshot",
            "accept": ".csv,text/csv"
        }
    }

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        """
        Get processor options

        These are dynamic for this processor: the 'column names' option is
        populated with the column names from the parent dataset, if available.

        :param DataSet parent_dataset:  Parent dataset
        :param user:  Flask User to which the options are shown, if applicable
        :return dict:  Processor options
        """
        options = cls.options

        models = config.get("dmi-service-manager.stormtrooper_models", user=user).split(",")
        options["model"]["options"] = {m: m for m in models}

        if parent_dataset is None:
            return options

        parent_columns = parent_dataset.get_columns()

        if parent_columns:
            parent_columns = {c: c for c in sorted(parent_columns)}
            options["text-column"].update({
                "type": UserInput.OPTION_CHOICE,
                "options": parent_columns,
            })

        return options

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow on datasets with columns (from which a prompt can be retrieved)
        """
        return config.get("dmi-service-manager.stormtrooper_enabled", False, user=user) and \
            config.get("dmi-service-manager.ab_server_address", False, user=user) and \
            module.get_columns()

    def process(self):
        """
        This takes a dataset and generates images for prompts retrieved from that dataset
        """

        model = self.parameters.get("model")
        textfield = self.parameters.get("text-column")

        # Make output dir
        staging_area = self.dataset.get_staging_area()
        output_dir = self.dataset.get_staging_area()

        # Initialize DMI Service Manager
        dmi_service_manager = DmiServiceManager(processor=self)

        # Check GPU memory available
        try:
            gpu_memory, info = dmi_service_manager.check_gpu_memory_available("stable_diffusion")
        except DmiServiceManagerException as e:
            return self.dataset.finish_with_error(str(e))
            staging_area.unlink()
            output_dir.unlink()

        if not gpu_memory:
            if info and info.get("reason") == "GPU not enabled on this instance of DMI Service Manager":
                self.dataset.update_status("DMI Service Manager GPU not enabled; using CPU")
            else:
                shutil.rmtree(staging_area)
                shutil.rmtree(output_dir)

                if info and int(info.get("memory", {}).get("gpu_free_mem", 0)) < 1000000:
                    return self.dataset.finish_with_error(
                        "DMI Service Manager currently too busy; no GPU memory available. Please try again later.")
                else:
                    return self.dataset.finish_with_error(
                        "Cannot connect to DMI Service Manager. Verify that this 4CAT server has access to it.")

        if self.parameters["shotstyle"] == "fewshot":
            # do we have examples?
            example_path = self.dataset.get_results_path().with_suffix(".importing")
            if not example_path.exists():
                return self.dataset.finish_with_error("Cannot open example file")

            labels = {}
            with example_path.open() as infile:
                dialect, has_header = sniff_csv_dialect(infile)
                reader = csv.reader(infile, dialect=dialect)
                for row in reader:
                    if row[0] not in labels:
                        labels[row[0]] = []
                    labels[row[0]].append(row[1])

            example_path.unlink()

        else:
            # if we have no examples, just include an empty list
            labels = {l.strip(): [] for l in self.parameters.get("categories").split(",") if l.strip()}


        # store labels in a file (since we don't know how much data this is)
        labels_path = staging_area.joinpath("labels.temp.json")
        with labels_path.open("w") as outfile:
            json.dump(labels, outfile)

        # Results should be unique to this dataset
        results_folder_name = f"images_{self.dataset.key}"
        file_collection_name = dmi_service_manager.get_folder_name(self.dataset)

        # prepare data for annotation
        data_path = staging_area.joinpath("data.temp.ndjson")
        with data_path.open("w", newline="") as outfile:
            for i, item in enumerate(self.source_dataset.iterate_items()):
                outfile.write(json.dumps({item.get("id", str(i)): item.get(textfield)}) + "\n")

        path_to_files, path_to_results = dmi_service_manager.process_files(staging_area,
                                                                           [data_path.name, labels_path.name],
                                                                           output_dir, file_collection_name,
                                                                           results_folder_name)

        # interface.py args
        data = {"timeout": (86400 * 7), "args": [
            "--model", model,
            "--output-dir", f"data/{path_to_results}",
            "--inputfile", f"data/{path_to_files.joinpath(dmi_service_manager.sanitize_filenames(data_path.name))}",
            "--labelfile", f"data/{path_to_files.joinpath(dmi_service_manager.sanitize_filenames(labels_path.name))}"
        ]}

        # Send request to DMI Service Manager
        self.dataset.update_status("Requesting service from DMI Service Manager...")
        api_endpoint = "stormtrooper"

        try:
            dmi_service_manager.send_request_and_wait_for_results(api_endpoint, data, wait_period=5)
        except DsmOutOfMemory:
            shutil.rmtree(staging_area)
            shutil.rmtree(output_dir)
            return self.dataset.finish_with_error(
                "DMI Service Manager ran out of memory; Try decreasing the number of prompts or try again or try again later.")
        except DmiServiceManagerException as e:
            shutil.rmtree(staging_area)
            shutil.rmtree(output_dir)
            return self.dataset.finish_with_error(str(e))

        # Download the result files
        self.dataset.update_status("Processing classified data...")
        dmi_service_manager.process_results(output_dir)

        # Output folder is basically already ready for archiving
        # Add a metadata JSON file before that though
        def make_filename(id, prompt):
            """
            Generate filename for generated image

            Should mirror the make_filename method in interface.py in the SD Docker.

            :param prompt_id:  Unique identifier, eg `54`
            :param str prompt:  Text prompt, will be sanitised, e.g. `Rasta Bill Gates`
            :return str:  For example, `54-rasta-bill-gates.jpeg`
            """
            safe_prompt = re.sub(r"[^a-zA-Z0-9 _-]", "", prompt).replace(" ", "-").lower()[:90]
            return f"{id}-{safe_prompt}.jpeg"

        self.dataset.update_status("Loading annotated data")
        with output_dir.joinpath("results.json").open() as infile:
            annotations = json.load(infile)
        self.dataset.update_status("Writing results")
        with self.dataset.get_results_path().open("w") as outfile:
            writer = None
            for i, item in enumerate(self.source_dataset.iterate_items()):
                row = {
                    "id": item.get("id", i),
                    textfield: item.get(textfield),
                    "category": annotations.get(item.get("id", str(i))) # str(i) because it is not recorded as an int in the annotations
                }
                if not writer:
                    writer = csv.DictWriter(outfile, fieldnames=row.keys())
                    writer.writeheader()

                writer.writerow(row)

        shutil.rmtree(staging_area)
        shutil.rmtree(output_dir)

        self.dataset.update_status(f"Categorised {len(annotations):,} item(s)")
        self.dataset.finish(len(annotations))

    @staticmethod
    def validate_query(query, request, user):
        """
        Validate input for a dataset query on the 4chan data source.

        Will raise a QueryParametersException if invalid parameters are
        encountered. Mutually exclusive parameters may also be sanitised by
        ignoring either of the mutually exclusive options.

        :param dict query:  Query parameters, from client-side.
        :param request:  Flask request
        :param User user:  User object of user who has submitted the query
        :return dict:  Safe query parameters
        """

        # this is the bare minimum, else we can't narrow down the full data set
        shotstyle = query.get("shotstyle")
        if shotstyle == "zeroshot":
            labels = query.get("categories")
            if not labels or len([l for l in labels if l.strip()]) < 2:
                raise QueryParametersException("At least two labels should be provided for text classification.")
        else:
            file = request.files["option-category-file"]
            if not file:
                raise QueryParametersException(
                    "No label file provided. A label file is required when using few-shot classification.")

            # we want a very specific type of CSV file!
            encoding = sniff_encoding(file)
            wrapped_file = io.TextIOWrapper(file, encoding=encoding)
            try:
                wrapped_file.seek(0)
                dialect, has_header = sniff_csv_dialect(wrapped_file)
                reader = csv.reader(wrapped_file, dialect=dialect) if not has_header else csv.DictReader(wrapped_file)
                row = next(reader)
                if len(list(row)) != 2:
                    raise QueryParametersException("The label file must have exactly two columns.")

            except UnicodeDecodeError:
                raise QueryParametersException("The label file does not seem to be a CSV file encoded with UTF-8. "
                                               "Save the file in the proper format and try again.")
            except csv.Error:
                raise QueryParametersException("Label file is not a well-formed CSV file.")
            finally:
                # we're done with the file
                wrapped_file.detach()

        return query

    def after_create(query, dataset, request):
        """
        Hook to execute after the dataset for this source has been created

        In this case, put the file in a temporary location so it can be
        processed properly by the related Job later.

        :param dict query:  Sanitised query parameters
        :param DataSet dataset:  Dataset created for this query
        :param request:  Flask request submitted for its creation
        """
        if query.get("shotstyle") != "fewshot":
            return

        file = request.files["option-category-file"]
        file.seek(0)
        with dataset.get_results_path().with_suffix(".importing").open("wb") as outfile:
            while True:
                chunk = file.read(1024)
                if len(chunk) == 0:
                    break
                outfile.write(chunk)
