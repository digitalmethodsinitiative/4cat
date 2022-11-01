"""
Extracts topics per model and top associated words
"""

from common.lib.helpers import UserInput
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

import pickle
import pyLDAvis.sklearn

__author__ = ["Dale Wahl"]
__credits__ = ["Dale Wahl"]
__maintainer__ = ["Dale Wahl"]
__email__ = "4cat@oilab.eu"


class VisualiseLDA(BasicProcessor):
    """
    Creates a webpage visualisation of an LDA model
    """
    type = "topic-model-vis"  # job type ID
    category = "Text analysis"  # category
    title = "Visualise LDA Model"  # title displayed in UI
    description = "Creates a visualisation of the chosen LDA model allowing exploration of the various words in each topic."  # description displayed in UI
    extension = "html"  # extension of result file, used internally and in UI

    references = [
        """Sievert, Carson, Shirley, Kenneth 2014. "LDAvis: A method for visualizing and interpreting topics" http://nlp.stanford.edu/events/illvi2014/papers/sievert-illvi2014.pdf""",
    ]

    options = {
                  "dimensionality": {
                      # https://pyldavis.readthedocs.io/en/latest/_modules/pyLDAvis/_prepare.html
                      "type": UserInput.OPTION_CHOICE,
                      "options": {
                          "pcoa": "Principal Coordinate Analysis (aka Classical Multidimensional Scaling)",
                          "mmds": "Metric Multidimensional Scaling",
                          "tsne": "T-distributed Stochastic Neighbor Embedding",
                      },
                      "default": "pcoa",
                      "help": "Multidimensionality reduction method",
                      "tooltip": "Please see references for additional information."
                  },
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
        Extracts topics per model and top associated words
        """
        mds = self.parameters.get("dimensionality")
        self.dataset.update_status("Unpacking topic models")
        staging_area = self.unpack_archive_contents(self.source_file)
        results = []
        processed = 0

        models = []
        for model_file in staging_area.glob("*.model"):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while extracting topic model tokens")

            self.dataset.update_status("Creating LDA visualisation for '%s'" % model_file.stem)
            self.dataset.update_progress(processed / self.source_dataset.num_rows)
            models.append(model_file.stem)
            processed += 1

            with model_file.open("rb") as infile:
                model = pickle.load(infile)

            with model_file.with_suffix(".vectors").open("rb") as infile:
                vectors = pickle.load(infile)

            with model_file.with_suffix(".vectoriser").open("rb") as infile:
                vectoriser = pickle.load(infile)

            LDAvis_prepared = pyLDAvis.sklearn.prepare(model, vectors, vectoriser, mds=mds, sort_topics=False)
            self.dataset.update_status("Saving LDA visualisation for '%s'" % model_file.stem)
            try:
                pyLDAvis.save_html(LDAvis_prepared, str(staging_area.joinpath('%s.html' % model_file.stem)))
            except TypeError as e:
                if 'Object of type complex is not JSON serializable' in e:
                    # Known issue: model contains complex (i.e. imaginary numbers). Possibly another type of dimensionality reduction can fix the issue or reducing number of topics.
                    # https://github.com/bmabey/pyLDAvis/issues/69
                    self.dataset.update_status("Data incompatible with dimensionality reduction method (appears to contain imaginary numbers). Try a different reduction method or decrease number of topics.", is_final=True)
                    self.dataset.finish(0)
                    return
                else:
                    raise e

        # Write HTML file
        with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
            output_file.write('<h1>LDA Models Visualised using <a href="https://pyldavis.readthedocs.io/en/latest/readme.html">pyLDAvis</a>')
            for model in models:
                output_file.write("<h1>Interval: %s</h2>" % model)
                with staging_area.joinpath(model+'.html').open('r') as html_file:
                    for line in html_file.readlines():
                        output_file.write(line)
        # Finish
        self.dataset.update_status("Finished")
        self.dataset.finish(1)
