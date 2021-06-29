"""
Request tags and labels from the Google Vision API for a given set of images
"""
import json
import keras_ocr
import threading
import time

import traceback

from common.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor
from common.lib.exceptions import ProcessorInterruptedException

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

class ImageTextDetector(BasicProcessor):
    """
    Image Text Detection

    This processor uses Optical Character Recognition (OCR) to first detect
    areas of an image that may contain text with the pretrained Character-Region
    Awareness For Text (CRAFT) detection model and then attempts to predict the
    text inside each area using Keras' implementation of a Convolutional
    Recurrent Neural Network (CRNN) for text recognition. Once words are
    predicted, an algorythm attempts to sort them into likely groupings based
    on locations within the original image.
    """
    type = "text_detection"  # job type ID
    category = "Metrics"  # category
    title = "Image Text Detection"  # title displayed in UI
    description = """
    This processor uses Optical Character Recognition (OCR) to first detect
    areas of an image that may contain text with the pretrained Character-Region
    Awareness For Text (CRAFT) detection model and then attempts to predict the
    text inside each area using Keras' implementation of a Convolutional
    Recurrent Neural Network (CRNN) for text recognition. Once words are
    predicted, an algorythm attempts to sort them into likely groupings based
    on locations within the original image.
    """ # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI
    accepts = ["image-downloader"]  # query types this post-processor accepts as input

    references = [
        "[Keras OCR Documentation]( https://keras-ocr.readthedocs.io/en/latest/)",
        "[CRAFT text detection model](https://github.com/clovaai/CRAFT-pytorch)",
        "[Keras CRNN text recognition model](https://github.com/kurapan/CRNN)"
    ]
    @classmethod
    def is_compatible_with(cls, dataset=None):
        """
        Allow processor on image sets

        :param DataSet dataset:  Dataset to determine compatibility with
        """
        return dataset.type == "image-downloader"

    input = "zip"
    output = "ndjson"

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "Images to process (0 = all)",
            "default": 0
        },
        # "model": {
		# 	"type": UserInput.OPTION_CHOICE,
		# 	"default": "xception",
		# 	"options": {
		# 		"xception": "1000 ImageNet categories Xception model",
		# 		"pepe_v1": "Pepe detection"
		# 	},
		# 	"help": "Choose which model to use for image predictions"
		# },
    }

    def process(self):
        """
        This takes a 4CAT image directory and runs each image through a text
        detection and recognition model. It then returns a list of text
        groupings (based on relative location of words on an image) with each
        text grouping containing a list of the words in that grouping.
        """

        # Load models
        # keras-ocr will automatically download pretrained
        # weights for the detector and recognizer.
        pipeline = keras_ocr.pipeline.Pipeline()

        max_images = convert_to_int(self.parameters.get("amount", 0), 100)
        total = self.source_dataset.num_rows if not max_images else min(max_images, self.source_dataset.num_rows)
        done = 0

        for image_file in self.iterate_archive_contents(self.source_file):
            if self.interrupted:
                raise ProcessorInterruptedException("Interrupted while processing Image Text Detector")

            done += 1
            self.dataset.update_status("Annotating image %i/%i" % (done, total))
            self.log.info(f"Filename: {image_file.name}")

            annotations = self.annotate_image(image_file, pipeline)

            if not annotations:
                continue

            annotations = {"file_name": image_file.name, **annotations}

            with self.dataset.get_results_path().open("a", encoding="utf-8") as outfile:
                self.log.info("Writing to file")
                outfile.write(json.dumps(str(annotations)) + "\n")

            if max_images and done >= max_images:
                break

        self.dataset.update_status("Annotations retrieved for %i images" % done)
        self.dataset.finish(done)

    def annotate_image(self, image_file, pipeline):
        """
        Get text from models

        :param Path image_file:  Path to file to annotate
        :param keras_ocr.pipeline pipeline:  Pipeline to run images through
        :return dict:  List of word groupings
        """

        try:
            self.log.info("Reading image")
            img = keras_ocr.tools.read(str(image_file))

            # All this for one damn timeout...
            prediction_holder = PredictionHolder(pipeline, self.log)
            self.log.info("Create thread")
            x = threading.Thread(target=prediction_holder.make_predictions, args=(img,))#, daemon=True)
            self.log.info("Start thread")
            x.start()

            # # JOIN WILL NOT WORK!
            # # program hangs and seems to ignore the timeout=60.0
            # self.log.info("Join thread")
            # x.join(60.0)

            # old school wait
            for i in range(60):
                if x.is_alive():
                    self.log.info(f"Waiting: {i}")
                    time.sleep(1)
                else:
                    self.log.info("Thread completed successfully")
                    break

            if x.is_alive():
                self.log.warning("Thread still running...")
                # By running as a daemon, if this process ends, the thread will also cease to exist
                # We could use threading.Event to tell it to terminate, but there is no loop or anything.
                # The thread starts keras_ocr.pipeline.recognize and that's all.
            # else:
            #     self.log.info("Thread completed successfully")

            if prediction_holder.predictions:
                self.log.info("Grouping text")
                text_groups = self.create_text_groups(prediction_holder.predictions)
                self.log.info("Removing position information")
                text = self.remove_positional_information(text_groups)
                return {'text' : text}
            else:
                self.log.info("No predictions returned")
                # No predictions made
                return False

        except Exception as e:
            # Certain image filetypes will not process; collecting types of errors to review
            self.log.info("Error")
            self.log.error(str(e))
            return False

    def create_text_groups(self, text_from_image):
        """
        This function cycles through predicted words and groups them based on
        their location on the image. It first finds words likely to be in a
        horizontal row, orders theses and checks to see if there are any large
        spaces between them (breaking them appart if there are). It then
        examines each group to see if there is another row closely following and
        groups them together.

        Through testing, using the height of a word seems to generally allow for
        accurate groupings however the size of text does not always correspond
        so neatly with the spacing between words and lines. Also of note: this
        method of grouping will not work with non horizontal words/rows.
        """
        texts = [SimpleBox(text) for text in text_from_image]
        # could sort texts by finding min of right bottom point (x + y) or, like, pythagorean theorem

        row_groups = []
        while texts:
            # grab first word
            text = texts[0]

            # collect all text on same "line"
            temp_row = [j for j in texts if abs(text.bottom - j.bottom) <= text.height/2]

           # sort the list in place in order of left to right
            temp_row.sort(key=lambda x: x.left, reverse=False)

            # Find large breaks within words
            # Initialize new list with first word
            temp_row_2 = [temp_row[0]]
            # Loop through rest of words in temp_row
            for index, word in enumerate(temp_row[1:]):
                # Is word close to previous?
                if abs(word.left - temp_row[index].right) < text.height/2:
                    temp_row_2.append(word)
                else:
                    break

            # add word group to collection
            row_groups.append(temp_row_2)
            # remove those words from possible words
            [texts.pop(texts.index(word)) for word in temp_row_2]

        # Now to check if rows are near each other... somehow...
        rows = [BigBox(row) for row in row_groups]

        text_groups = []

        while rows:
            matching_row = rows[0]

            group = [matching_row]
            for new_row in rows[1:]:
                # is top of new_row near bottom of our row?
                if (new_row.top - matching_row.bottom) < (matching_row.height*.75):
                    # and is center of row within the margins of our row?
                    if  matching_row.left < new_row.center < matching_row.right:
                        group.append(new_row)
                        matching_row = new_row

            text_groups.append(group)
            # remove those rows from possible rows
            [rows.pop(rows.index(row)) for row in group]

        return text_groups

    def remove_positional_information(self, text_groups):
        """
        Takes the result from create_text_groups and returns only the text.

        TODO: build this object in the create_text_groups function to prevent
        this double loop.
        """
        text = {}
        text['groupings'] = [[[word.word for word in line.original] for line in group] for group in text_groups]
        text['raw_text'] = '\n\n'.join(['\n'.join([' '.join([word.word for word in line.original]) for line in group]) for group in text_groups])
        return text

class SimpleBox():
    """
    This class reorganizes words to find location attributes
    """
    def __init__(self, stupid_box):
        self.word = stupid_box[0]
        self.top = min([i[1] for i in stupid_box[1]])
        self.left = min([i[0] for i in stupid_box[1]])
        self.bottom = max([i[1] for i in stupid_box[1]])
        self.right = max([i[0] for i in stupid_box[1]])
        self.height = self.bottom - self.top

class BigBox():
    """
    Similarly to SimpleBox, this represents a grouping of many SimpleBoxes
    """
    def __init__(self, list_of_simple_boxes):
        self.original = list_of_simple_boxes
        self.top = min([i.top for i in list_of_simple_boxes])
        self.left = min([i.left for i in list_of_simple_boxes])
        self.bottom = max([i.bottom for i in list_of_simple_boxes])
        self.right = max([i.right for i in list_of_simple_boxes])
        self.height = self.bottom - self.top
        self.center = ((self.right - self.left)/2) + self.left

class PredictionHolder():
    """
    To pass to thread for prediction. A new holder should be created for each
    prediction.
    """
    def __init__(self, pipeline, log):
        self.predictions = None
        self.pipeline = pipeline
        self.log = log

    def make_predictions(self, img):
        self.log.debug("Making predictions")
        self.predictions = self.pipeline.recognize([img])[0]
        self.log.debug("Predictions complete")
