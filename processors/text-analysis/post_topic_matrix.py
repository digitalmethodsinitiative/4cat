"""
Extracts topics per model and top associated words
"""

from common.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException, ProcessorException

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
    title = "Post/Topic matrix"  # title displayed in UI
    description = "Uses the LDA model to predict to which topic each item or sentence belongs and creates a CSV file showing this information. Each line represents one 'document'; if tokens are grouped per 'item' and only one column is used (e.g. only the 'body' column), there is one row per post/item, otherwise a post may be represented by multiple rows (for each sentence and/or column used)."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    options = {
        "include_top_features": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Include top 5 words in topic header",
            "tooltip": 'This may be useful in better understanding your topics.',
        }
    }

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on topic models

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type == "topic-modeller"

    def process(self):
        """
        Extracts metadata and connects to original dataset
        """
        # Find metadata files
        self.dataset.update_status("Collecting token and model metadata")
        token_metadata = None
        model_metadata = None
        staging_area = self.dataset.get_staging_area()
        # Unzip archived files
        with zipfile.ZipFile(self.source_file, "r") as archive_file:
            # Extract our metadata files
            archive_file.extract('.token_metadata.json', staging_area)
            archive_file.extract('.model_metadata.json', staging_area)
            # Load them
            with staging_area.joinpath('.token_metadata.json').open("rb") as metadata_file:
                token_metadata = json.load(metadata_file)
            with staging_area.joinpath('.model_metadata.json').open("rb") as metadata_file:
                model_metadata = json.load(metadata_file)

        if token_metadata is None or model_metadata is None:
            self.dataset.update_status("Metadata files not found; cannot perform analysis (if Tolenise is from previous 4CAT version; try starting over from there again)", is_final=True)
            self.dataset.update_status(0)
            return

        # Grab the parameters from out metadata files
        token_metadata_parameters = token_metadata.pop('parameters')
        model_metadata_parameters = model_metadata.pop('parameters')

        # Collect column names of matrix
        post_column_names = list(set(['id', 'thread_id', 'timestamp', 'author', 'body'] + token_metadata_parameters.get('columns')))
        model_column_names = ['post_id', 'document_id', 'interval']
        # Check if multiple documents exist per post/item and add 'document' column if needed
        if token_metadata_parameters.get('grouped_by') != 'item' or len(token_metadata_parameters.get('columns')) > 1:
            model_column_names.append('document')
            multiple_docs_per_post = True
        else:
            multiple_docs_per_post = False
        # Add topic columns for each interval/model
        for interval in token_metadata_parameters.get('intervals'):
            if self.parameters.get('include_top_features'):
                model_column_names += [interval + '_topic_' + str(i+1) + '_' + '-'.join([f for f in model_metadata[interval+'.json']['model_topics'][str(i)]['top_five_features']]) for i in range(model_metadata_parameters.get('topics'))]
            else:
                model_column_names += [interval + '_topic_' + str(i+1) for i in range(model_metadata_parameters.get('topics'))]

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
                token_data = token_metadata[post.get('id')]
                model_data = model_metadata[token_data.get('filename')]
                interval = token_data['interval']

                combined_data = {'post_id':post.get('id'), 'interval':interval}
                # Add original post data
                for post_column in post_column_names:
                    combined_data[post_column] = post.get(post_column)

                # Add topic data
                # Collect relevant topics for the model used on this post
                # NOTE: adding 1 to the topic numbers to be constent with topic_words processor (and normal people don't start counting with 0)
                if self.parameters.get('include_top_features'):
                    related_topic_columns = [interval + '_topic_' + str(i+1) + '_' + '-'.join([f for f in model_metadata[interval+'.json']['model_topics'][str(i)]['top_five_features']]) for i in range(model_metadata_parameters.get('topics'))]
                else:
                    related_topic_columns = [interval + '_topic_' + str(i+1) for i in range(model_metadata_parameters.get('topics'))]

                # Collect predictions for post
                for document_number in token_data['document_numbers']:
                    combined_data['id'] = post.get('id') + '-' + str(document_number)
                    combined_data['document_id'] = document_number

                    # Add specific document resulting in prediction if unclear (i.e. multiple documents per item/post)
                    if multiple_docs_per_post:
                        combined_data['document'] = token_data['documents'][str(document_number)]

                    doc_predictions = model_data['predictions'][str(document_number)]
                    for i, topic in enumerate(related_topic_columns):
                        combined_data[topic] = doc_predictions[str(i)]


                    writer.writerow(combined_data)
                    index += 1

        self.dataset.update_status("Results saved")
        self.dataset.finish(index)
