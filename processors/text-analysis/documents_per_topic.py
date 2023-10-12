"""
Extracts topics per model and top associated words
"""

from backend.lib.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

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
    type = "document_count"  # job type ID
    category = "Text analysis"  # category
    title = "Count documents per topic"  # title displayed in UI
    description = "Uses the LDA model to predict to which topic each item or sentence belongs and counts as belonging to whichever topic has the highest probability."  # description displayed in UI
    extension = "csv"  # extension of result file, used internally and in UI

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on topic models

        :param module: Module to determine compatibility with
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
            zip_filenames = archive_file.namelist()
            if any([filename not in zip_filenames for filename in ['.token_metadata.json', '.model_metadata.json']]):
                self.dataset.update_status(
                    "Metadata files not found; cannot perform analysis (if Tolenise is from previous 4CAT version; try running previous analysis again)",
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

        # Start writing result file
        self.dataset.update_status("Collecting model predictions")

        topics_count = {}
        # Prepopulate in case a topic has no documents (i.e., topic model is poor)
        for interval in  token_metadata_parameters.get('intervals'):
            for topic_number in range(model_metadata_parameters.get('topics')):
                topics_count[interval+str(topic_number)] = 0

        # Loop through the token metadata and count documents in each topic
        for post_id, token_data in token_metadata.items():
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while writing results file")

            # Grab model metadata related to post
            model_data = model_metadata[token_data.get('filename')]
            interval = token_data['interval']

            # Collect predictions for post
            for document_number in token_data['document_numbers']:
                doc_predictions = model_data['predictions'][str(document_number)]

                top_topics = {f: doc_predictions[f] for f in sorted(doc_predictions, key=lambda k: doc_predictions[k], reverse=True)[:2]}
                test_top_two = [weight for topic_number, weight in top_topics.items()]
                if test_top_two[0] == test_top_two[1]:
                    self.dataset.log('Document %s-%s equally probable in two or more topics; skipping' % (post_id, str(document_number)))

                topic_number = str([topic_number for topic_number, weight in top_topics.items()][0])
                topics_count[interval + topic_number] += 1

        # Reformat model data
        topics = []
        for token_filename, model_data in model_metadata.items():
            for topic in model_data['model_topics'].values():
                topics.append({
                                'topic_interval': token_filename.rstrip('.json'),
                                'topic_number': topic['topic_index'] + 1, # Adding 1 to conform with other processors
                                'top_five_features': ', '.join([f+': '+str(w) for f,w in topic['top_five_features'].items()]),
                                'number_of_documents': topics_count[token_filename.rstrip('.json') + str(topic['topic_index'])],
                                })

        self.write_csv_items_and_finish(topics)
