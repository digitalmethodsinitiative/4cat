"""
Request tags and labels from the Google Vision API for a given set of images
"""
import json
import csv

from clarifai_grpc.grpc.api import service_pb2, resources_pb2, service_pb2_grpc
from clarifai_grpc.grpc.api.status import status_code_pb2
from clarifai_grpc.channel.clarifai_channel import ClarifaiChannel

from common.lib.helpers import UserInput, convert_to_int
from backend.lib.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

csv.field_size_limit(1024 * 1024 * 1024)


class ClarifaiAPIFetcher(BasicProcessor):
    """
    Clarifai API data fetcher

    Request tags and labels from the Clarifai API for a given set of images
    """
    type = "clarifai-api"  # job type ID
    category = "Post metrics"  # category
    title = "Clarifai API Analysis"  # title displayed in UI
    description = "Use the Clarifai API to annotate images with tags and labels identified via machine learning. " \
                  "One request will be made per image per annotation type. Note that this is NOT a free service and " \
                  "requests will be credited by Clarifai to the owner of the API token you provide!"  # description displayed in UI
    extension = "ndjson"  # extension of result file, used internally and in UI

    references = [
        "[Clarifai](https://www.clarifai.com/)",
        "[Clarifai API Pricing & Free Usage Limits](https://www.clarifai.com/pricing)",
        "[Clarifai model browser](https://clarifai.com/clarifai/main/models)"
    ]

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on image sets

        :param module: Module to determine compatibility with
        """
        return module.type.startswith("image-downloader")

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "Images to process (0 = all)",
            "cache": True,
            "sensitive": True,
            "default": 0
        },
        "api_key": {
            "type": UserInput.OPTION_TEXT,
            "help": "API Key",
            "cache": True,
            "sensitive": True,
            "tooltip": "The API Key for the Clarifai account you want to query with. You can generate and find this"
                       "key on the API dashboard."
        },
        "models": {
            "type": UserInput.OPTION_MULTI,
            "help": "Models",
            "tooltip": "Which models to use for recognition? More models = more API calls = potentially more costs. "
                       "See the model browser in processor references for more details on each model.",
            "options": {
                "general-image-recognition": "General Concept Recognition (general-image-recognition)",
                "apparel-recognition": "Clothing & Apparal (apparel-recognition)",
                "color-recognition": "Dominant color recognition (color-recognition)",
                "celebrity-face-detection": "Celebrity faces (celebrity-face-detection)",
                "food-item-recognition": "Food items (food-item-recognition)",
                "moderation-recognition": "Inappropriate content (moderation-recognition)",
                "nsfw-recognition": "NSFW content (mostly nudity, nsfw-recognition)",
                "texture-recognition": "Materials & textures (texture-recognition)"
            },
            "default": ["general-image-recognition"]
        }
    }

    def process(self):
        """
        This takes a 4CAT results file as input, and outputs a new CSV file
        with one column with image hashes, one with the first file name used
        for the image, and one with the amount of times the image was used
        """
        api_key = self.parameters.get("api_key")
        #application_id = self.parameters.get("application_id")

        models = self.parameters.get("models")
        if type(models) is str:
            models = [models]

        if not models:
            return self.dataset.finish_with_error(
                "No models selected; select at least one model for concept recognition.")

        metadata = (("authorization", f"Key {api_key}"),)
        stub = service_pb2_grpc.V2Stub(ClarifaiChannel.get_grpc_channel())
        limit = convert_to_int(self.parameters.get("amount"), 10)
        buffer = {}
        batch_size = 16

        num_images = self.source_dataset.num_rows - 1  # .metadata.json
        total_annotations = (num_images if limit == 0 else min(limit, num_images)) * len(models)
        errors = 0
        processed = 0
        annotated = 0

        # send batched requests per model
        for model_id in models:
            iterator = self.iterate_archive_contents(self.source_file)
            batch = []
            images_names = {}
            looping = True
            while looping:
                send_batch = False
                image = None
                try:
                    image = next(iterator)
                except StopIteration:
                    # all images processed, send batch and stop
                    send_batch = True
                    looping = False

                if len(batch) == batch_size or (limit and processed >= limit):
                    send_batch = True

                if image:
                    if image.name.startswith("."):
                        # .metadata.json
                        continue

                    # we can attach the image as a binary file
                    with image.open("rb") as infile:
                        encoded_image = infile.read()

                    batch.append(resources_pb2.Input(
                        data=resources_pb2.Data(image=resources_pb2.Image(
                            base64=encoded_image
                        ))
                    ))

                    images_names[len(batch) - 1] = image.name

                # send batch of images to the Clarifai API
                if send_batch and batch:
                    request = service_pb2.PostModelOutputsRequest(
                        model_id=model_id,
                        # user_app_id=resources_pb2.UserAppIDSet(app_id=application_id),
                        inputs=batch,
                    )

                    response = stub.PostModelOutputs(request, metadata=metadata)
                    processed += len(response.outputs)

                    self.dataset.update_progress(processed / total_annotations)
                    self.dataset.update_status(f"Collected {processed:,} of {total_annotations:,} annotations")

                    if response.status.code == status_code_pb2.MIXED_STATUS:
                        # handled individually per image
                        # invalid format for example
                        pass
                    elif response.status.code != status_code_pb2.SUCCESS:
                        # this is bad!
                        self.dataset.log(f"Error fetching {model_id} annotations from Clarifai annotated ({response.status.code}"
                                                   f"/{response.status.description})")
                        return self.dataset.finish_with_error(f"Error connecting to Clarifai ({response.status.description}), stopping.")

                    # collect annotated concepts
                    for index, output in enumerate(response.outputs):
                        image_name = images_names[index]
                        if output.status.code != status_code_pb2.SUCCESS:
                            self.dataset.update_status(f"Image {image_name} could not be annotated ({output.status.description}), skipping")
                            errors += 1
                            continue

                        annotated += 1
                        if image_name not in buffer:
                            buffer[image_name] = {}

                        # add concepts to buffer to write them to the result
                        # file later
                        buffer[image_name][model_id] = {concept.name: concept.value for concept in output.data.concepts}

                    images_names = {}
                    batch = []

        # save the buffered results (we do this only now so we can also store
        # combined annotations)
        with self.dataset.get_results_path().open("w", encoding="utf-8") as outfile:
            for image, annotations in buffer.items():
                all_annotations = {}
                for model_annotations in annotations.values():
                    all_annotations.update(model_annotations)

                item = {
                    "image": image,
                    **annotations,
                    "combined": all_annotations
                }
                outfile.write(json.dumps(item) + "\n")

        if errors:
            self.dataset.update_status(f"Collected {annotated} annotations, {errors} skipped - see dataset log for details",
                                       is_final=True)
        else:
            self.dataset.update_status(f"Collected {annotated} annotations", is_final=True)

        self.dataset.finish(len(buffer))
