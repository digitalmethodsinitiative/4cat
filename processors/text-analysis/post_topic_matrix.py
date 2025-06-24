"""
Extracts topics per model and top associated words
"""

from common.lib.helpers import UserInput
from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

import csv
import json
import zipfile

__author__ = ["Dale Wahl"]
__credits__ = ["Dale Wahl"]
__maintainer__ = ["Dale Wahl"]
__email__ = "4cat@oilab.eu"


class TopicModelWordExtractor(BasicProcessor):
    """
    Extracts topics per model and top associated words
    """
    type = "document_topic_matrix"  # job type ID
    category = "Text analysis"  # category
    title = "Post/Topic matrix (predict which posts belong to which topics)"  # title displayed in UI
    description = ("Uses the LDA model to predict which topic each item or sentence belongs to. Creates a CSV file where "
                   "each line represents one 'document'; if tokens are grouped per 'item' and only one column is used "
                   "(e.g. only the 'body' column), there is one row per post/item, otherwise a post may be represented "
                   "by multiple rows (for each sentence and/or column used).")  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    followups = []

    options = {
        "include_top_features": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Include top 5 words in topic header",
            "tooltip": 'This may be useful in better understanding your topics.',
        },
        "columns": {
            "type": UserInput.OPTION_MULTI,
            "help": "Extra column(s) to include from original data",
            "default": ["id"],
            "tooltip": "Note: 'id', 'thread_id', 'timestamp', 'author', 'body' and any tokenized columns are always "
                       "included."
        },
		"save_annotations": {
			"type": UserInput.OPTION_TOGGLE,
			"help": "Add topic weights to top dataset",
			"default": False
		}
    }

    @classmethod
    def get_options(cls, parent_dataset=None, config=None):
        """
        Get processor options

        This method by default returns the class's "options" attribute, or an
        empty dictionary. It can be redefined by processors that need more
        fine-grained options, e.g. in cases where the availability of options
        is partially determined by the parent dataset's parameters.

        :param config:
        :param DataSet parent_dataset:  An object representing the dataset that
        the processor would be run on
can
        be used to show some options only to privileges users.
        """
        options = cls.options

        if parent_dataset:
            top_dataset = parent_dataset.top_parent()
            if top_dataset.get_columns():
                columns = top_dataset.get_columns()
                options["columns"]["type"] = UserInput.OPTION_MULTI
                options["columns"]["inline"] = True
                options["columns"]["options"] = {v: v for v in columns}
                options["columns"]["default"] = ["body"]

        return options

    @classmethod
    def is_compatible_with(cls, module=None, config=None):
        """
        Allow processor on topic models

        :param module: Module to determine compatibility with
        :param ConfigManager|None config:  Configuration reader (context-aware)
        """
        return module.type == "topic-modeller"

    def process(self):
        """
        Extracts metadata and connects to original dataset
        """
        # Find metadata files
        self.dataset.update_status("Collecting token and model metadata")

        save_annotations = self.parameters.get("save_annotations", False)
        annotations = []

        staging_area = self.dataset.get_staging_area()
        # Unzip archived files
        with zipfile.ZipFile(self.source_file, "r") as archive_file:
            zip_filenames = archive_file.namelist()
            if any([filename not in zip_filenames for filename in ['.token_metadata.json', '.model_metadata.json']]):
                self.dataset.update_status(
                    "Metadata files not found; cannot perform analysis (if Tolenise is from previous 4CAT version; try "
                    "running previous analysis again)",
                    is_final=True)
                self.dataset.update_status(0)
                return

            # Extract our metadata files
            archive_file.extract('.token_metadata.json', staging_area)
            archive_file.extract('.model_metadata.json', staging_area)

            # Load them
            with staging_area.joinpath('.token_metadata.json').open("rb") as metadata_file:
                token_metadata = json.load(metadata_file)
            with staging_area.joinpath('.model_metadata.json').open("rb") as metadata_file:
                model_metadata = json.load(metadata_file)

        # Grab the parameters from out metadata files
        token_metadata_parameters = token_metadata.pop('parameters')
        model_metadata_parameters = model_metadata.pop('parameters')

        # Check token metadata is correct format
        first_key = next(iter(token_metadata))
        for interval, token_data in token_metadata[first_key].items():
            if any([required_keys not in token_data for required_keys in ['interval', 'document_numbers', 'filename']]):
                self.dataset.finish_with_error("Token metadata is not in correct format; please re-run tokenise-posts "
                                               "processor if not run since 4CAT update")
                return
            break

        # Collect column names of matrix
        post_column_names = list(set(['id', 'thread_id', 'timestamp', 'author', 'body'] +
                                     self.parameters.get('columns', []) + token_metadata_parameters.get('columns')))
        model_column_names = ['post_id', 'document_id', 'interval', 'top_topic(s)']

        # Check if multiple documents exist per post/item and add a note if so
        # TODO: We do not have the actual documents; we would either need to store them when tokenized or re-do the
        #  sentence split and, possibly, the columns if multiple were used.
        if token_metadata_parameters.get('grouped_by') != 'item' or len(token_metadata_parameters.get('columns')) > 1:
            model_column_names.append('original_document_split')
            multiple_docs_per_post = True
        else:
            multiple_docs_per_post = False
        # Add topic columns for each interval/model
        for interval in token_metadata_parameters.get('intervals'):
            if self.parameters.get('include_top_features'):
                model_column_names += [interval + '_topic_' + str(i+1) + '_' + '-'.join(
                    [f for f in model_metadata[interval+'.json']['model_topics'][str(i)]['top_five_features']]
                ) for i in range(model_metadata_parameters.get('topics'))]
            else:
                model_column_names += [interval + '_topic_' + str(i+1)
                                       for i in range(model_metadata_parameters.get('topics'))]

        # Start writing result file
        self.dataset.update_status("Collecting model predictions")
        index = 0
        with self.dataset.get_results_path().open("w", encoding="utf-8", newline='') as results:
            writer = csv.DictWriter(results, fieldnames=post_column_names + model_column_names)
            writer.writeheader()

            # Loop through the source dataset
            for post in self.dataset.top_parent().iterate_items(self):
                if self.interrupted:
                    raise ProcessorInterruptedException("Interrupted while writing results file")

                # Grab metadata related to post
                if post.get('id') not in token_metadata:
                    # post has no tokens...
                    continue

                post_intervals = token_metadata[str(post.get('id'))]

                # Posts may have multiple intervals
                for interval, token_data in post_intervals.items():
                    model_data = model_metadata[token_data.get('filename')]
                    interval = token_data['interval']

                    combined_data = {'post_id': str(post.get('id')), 'interval':interval}
                    # Add original post data
                    for post_column in post_column_names:
                        combined_data[post_column] = post.get(post_column)

                    # Add topic data
                    # Collect relevant topics for the model used on this post
                    # NOTE: adding 1 to the topic numbers to be constent with topic_words processor (and normal people
                    # don't start counting with 0)
                    if self.parameters.get('include_top_features'):
                        related_topic_columns = [interval + '_topic_' + str(i+1) + '_' + '-'.join(
                            [f for f in model_metadata[interval+'.json']['model_topics'][str(i)]['top_five_features']]
                        ) for i in range(model_metadata_parameters.get('topics'))]
                    else:
                        related_topic_columns = [interval + '_topic_' + str(i+1)
                                                 for i in range(model_metadata_parameters.get('topics'))]

                    # Collect predictions for post
                    for document_number in token_data['document_numbers']:
                        combined_data['id'] = str(post.get('id')) + '-' + str(document_number)
                        combined_data['document_id'] = document_number

                        # Note if original document was split (by sentence or using multiple columns in tokenizer)
                        # resulting in prediction if unclear (i.e. multiple documents per item/post)
                        # TODO: Either store the original document when tokenized or re-do the sentance split and,
                        #  possibly, the columns if multiple were used.
                        #  The second seems unfeasible, but the first would require somehow storing the split documents
                        #  and then retrieving them here by post_id and document_id; give me a database guys!
                        if multiple_docs_per_post:
                            combined_data['original_document_split'] = token_data['multiple_docs']

                        doc_predictions = model_data['predictions'][str(document_number)]

                        # add one to topic key here as well
                        top_topics = ', '.join([str(int(key) + 1)
                                               for key, value in doc_predictions.items()
                                               if value == max(doc_predictions.values())])
                        combined_data['top_topic(s)'] = top_topics
                        # Potentially add most likely topic as annotation
                        if save_annotations:
                            annotations.append({
                                "label": "top_topic(s)",
                                "value": top_topics,
                                "item_id": post.get("id")
                            })

                        for i, topic in enumerate(related_topic_columns):
                            combined_data[topic] = doc_predictions[str(i)]

                            # Potentially add topic weights as annotations
                            if save_annotations:
                                annotations.append({
                                    "label": topic,
                                    "value": doc_predictions[str(i)],
                                    "item_id": post.get("id")
                                    })

                        writer.writerow(combined_data)
                        index += 1

        if save_annotations:
            self.save_annotations(annotations)

        self.dataset.update_status("Results saved")
        self.dataset.finish(index)
