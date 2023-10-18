"""
Create an PixPlot of downloaded images
"""
import shutil
import json
from datetime import datetime
import csv
import os
from urllib.parse import unquote
from werkzeug.utils import secure_filename

from common.config_manager import config
from common.lib.dmi_service_manager import DmiServiceManager, DsmOutOfMemory, DmiServiceManagerException
from common.lib.helpers import UserInput, convert_to_int
from backend.lib.processor import BasicProcessor

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class PixPlotGenerator(BasicProcessor):
    """
    PixPlot generator

    Create an PixPlot from the downloaded images in the dataset
    """
    type = "pix-plot"  # job type ID
    category = "Visual"  # category
    title = "Create PixPlot visualisation"  # title displayed in UI
    description = "Put all images from an archive into a PixPlot visualisation: an explorable map of images " \
                  "algorithmically grouped by similarity."
    extension = "html"  # extension of result file, used internally and in UI

    references = [
        "[PixPlot](https://pixplot.io/)",
        "[Parameter documentation](https://pixplot.io/docs/api/parameters.html)"
    ]

    # PixPlot requires a minimum number of photos to be created
    # This is currently due to the clustering algorithm which creates 12 clusters
    min_photos_needed = 12

    config = {
        "dmi-service-manager.da_pixplot-intro-1": {
            "type": UserInput.OPTION_INFO,
            "help": "Explore images with [Yale Digital Humanities Lab Team's PixPlot](https://github.com/digitalmethodsinitiative/dmi_pix_plot).",
        },
        "dmi-service-manager.db_pixplot_enabled": {
            "type": UserInput.OPTION_TOGGLE,
            "default": False,
            "help": "Enable PixPlot Image Viewer",
        },
        "dmi-service-manager.dc_pixplot_num_files": {
            "type": UserInput.OPTION_TEXT,
            "coerce_type": int,
            "default": 0,
            "help": "PixPlot max number of images",
            "tooltip": "Use '0' to allow unlimited number"
        },
    }


    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        # Update the amount max and help from config
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of images",
                "default": 1000,
                "tooltip": "Increasing this can easily lead to very long-running processors."
            },
            "intro-plot-options": {
                "type": UserInput.OPTION_INFO,
                "help": "The below options will help configure your plot. Note that full images are always available by "
                        "clicking on the thumbnails (you will also find metadata related to the source of the image "
                        "there). Large datasets run better with smaller thumbnails."
            },
            "image_size": {
                "type": UserInput.OPTION_CHOICE,
                "help": "Thumbnail Size",
                "options": {
                    "10": "10px tiny",
                    "32": "32px small",
                    "64": "64px normal",
                    "128": "128px large",
                    "256": "256px X-large",
                },
                "default": "64"
            },
            "intro-plot-neighbours": {
                "type": UserInput.OPTION_INFO,
                "help": "Nearest neighbors (n_neighbors): small numbers identify local clusters, larger numbers "
                        "create a more global shape. Large datasets may benefit from have higher values (think how many "
                        "alike pictures could make up a cluster)."
            },
            "n_neighbors": {
                "type": UserInput.OPTION_TEXT,
                "help": "Nearest Neighbors",
                "tooltip": "Larger datasets may benefit from a larger value",
                "min": 2,
                "max": 200,
                "default": 15
            },
            "intro-plot-mindist": {
                "type": UserInput.OPTION_INFO,
                "help": "Minimum Distance (min_dist): determines how tightly packed images can be with one and other "
                        "(i.e., small numbers (0.0001-0.001) are tightly packed, and larger (0.05-0.2) disperse."
            },
            "min_dist": {
                "type": UserInput.OPTION_TEXT,
                "help": "Minimum Distance between images",
                "tooltip": "Small values often work best",
                "min": 0.0001,
                "max": 0.99,
                "default": 0.01
            },
        }

        max_number_images = int(config.get("dmi-service-manager.dc_pixplot_num_files", 10000, user=user))
        if max_number_images == 0:
            options["amount"]["help"] = options["amount"]["help"] + " (max: all available)"
            options["amount"]["min"] = 0
            options["amount"]["tooltip"] = options["amount"]["tooltip"] + " 0 allows as many images as available."
        else:
            options["amount"]["help"] = options["amount"]["help"] + f" (max: {max_number_images})"
            options["amount"]["min"] = 1
            options["amount"]["max"] = max_number_images

        return options

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on token sets;
        Checks if pix-plot.server_url set

        :param module: Dataset or processor to determine compatibility with
        """
        return config.get("dmi-service-manager.db_pixplot_enabled", False, user=user) and \
               config.get("dmi-service-manager.ab_server_address", False, user=user) and \
               module.type.startswith("image-downloader")

    def process(self):
        """
        This takes a 4CAT results file as input, copies the images to a temp
        folder,
        """
        self.dataset.update_status("Reading source file")

        # Are there any available images?
        if self.source_dataset.num_rows == 0:
            self.dataset.update_status("No images available to render to PixPlot.", is_final=True)
            self.dataset.finish(0)
            return

        # Unpack the images into a staging_area
        self.dataset.update_status("Unzipping images")
        staging_area = self.unpack_archive_contents(self.source_file)

        # Collect filenames (skip .json metadata files)
        image_filenames = [filename for filename in os.listdir(staging_area) if
                           filename.split('.')[-1] not in ["json", "log"]]
        if self.parameters.get("amount", 100) != 0:
            image_filenames = image_filenames[:self.parameters.get("amount", 100)]
        total_image_files = len(image_filenames)

        # Check to ensure enough photos will be uploaded to create a PixPlot
        if total_image_files < self.min_photos_needed:
            self.dataset.update_status(
                "Minimum of %i photos needed for a PixPlot to be created" % self.min_photos_needed, is_final=True)
            self.dataset.finish(0)
            return

        # Gather metadata
        self.dataset.update_status("Collecting metadata")
        metadata_file_path = self.format_metadata(staging_area)

        # Make output dir
        output_dir = self.dataset.get_results_folder_path()
        output_dir.mkdir(exist_ok=True)

        # Initialize DMI Service Manager
        dmi_service_manager = DmiServiceManager(processor=self)

        # Results should be unique to this dataset
        server_results_folder_name = f"4cat_results_{self.dataset.key}"
        # Files can be based on the parent dataset (to avoid uploading the same files multiple times)
        file_collection_name = dmi_service_manager.get_folder_name(self.source_dataset)

        path_to_files, path_to_results = dmi_service_manager.process_files(staging_area, image_filenames + [metadata_file_path], output_dir,
                                                                           file_collection_name, server_results_folder_name)

        # PixPlot
        # Create json package for creation request
        data = {'args': ['--images', f"data/{path_to_files}/*",
                         '--out_dir', f"data/{path_to_results}",
                         '--metadata', f"data/{path_to_files}/{metadata_file_path.name}"]}

        # Additional options for PixPlot
        cell_size = self.parameters.get('image_size')
        n_neighbors = self.parameters.get('n_neighbors')
        min_dist = self.parameters.get('min_dist')
        data['args'] += ['--cell_size', str(cell_size), '--n_neighbors', str(n_neighbors), '--min_dist', str(min_dist)]

        # Increase timeout (default is 3600 seconds)
        data['timeout'] = 21600

        # Send request to DMI Service Manager
        self.dataset.update_status(f"Requesting service from DMI Service Manager...")
        api_endpoint = "pixplot"
        try:
            dmi_service_manager.send_request_and_wait_for_results(api_endpoint, data, wait_period=30, check_process=False)
        except DsmOutOfMemory:
            self.dataset.finish_with_error(
                "DMI Service Manager ran out of memory; Try decreasing the number of images or try again or try again later.")
            return
        except DmiServiceManagerException as e:
            self.dataset.finish_with_error(str(e))
            return

        self.dataset.update_status("Processing PixPlot results...")
        # Download the result files
        dmi_service_manager.process_results(output_dir)

        # Results HTML file redirects to output_dir/index.html
        plot_url = ('https://' if config.get("flask.https") else 'http://') + config.get("flask.server_name") + '/result/' + f"{os.path.relpath(self.dataset.get_results_folder_path(), self.dataset.folder)}/index.html"
        html_file = self.get_html_page(plot_url)

        # Write HTML file
        with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
            output_file.write(html_file)

        # Finish
        self.dataset.update_status("Finished")
        self.dataset.finish(1)

        # Clean up staging area
        if staging_area:
            shutil.rmtree(staging_area)

    def format_metadata(self, temp_path):
        """
        Returns metadata.csv file

        Columns for PixPlot metadata can be:
        filename |	the filename of the image
        category |	a categorical label for the image
        tags |	a pipe-delimited list of categorical tags for the image
        description |	a plaintext description of the image's contents
        permalink |	a link to the image hosted on another domain
        year |	a year timestamp for the image (should be an integer)
        label |	a categorical label used for supervised UMAP projection
        lat |	the latitudinal position of the image
        lng |	the longitudinal position of the image

        We have a folder with image filenames, a top_downloads csv with filenames and post ids, and a source file with
        the action information needed. Annoyingly the source file is by far the largest file so we do not want to hold
        it in memory. Instead we will loop through it and build the metadata file as we go.

        """
        # Get image data
        if not os.path.isfile(os.path.join(temp_path, '.metadata.json')):
            # No metadata
            return False

        with open(os.path.join(temp_path, '.metadata.json')) as file:
            image_data = json.load(file)

        # Images can belong to multiple posts, so we must build this file as we go
        images = {}

        # Reformat image_data to access by filename and begin metadata
        post_id_image_dictionary = {}
        successful_image_count = 0
        for url, data in image_data.items():
            # Check if image successfully downloaded for image
            if data.get('success') and data.get('filename') is not None and data.get('post_ids'):
                successful_image_count += 1
                # if no filename, bad metadata; file was not actually downloaded, fixed in 9b603cd1ecdf97fd92c3e1c6200e4b6700dc1e37

                # dmi_pix_plot API uses secure_filename while pixplot.py (in PixPlot library) uses clean_filename
                filename = self.clean_filename(secure_filename(data.get('filename')))

                for post_id in data.get('post_ids'):
                    # Add key to post ID dictionary
                    if post_id in post_id_image_dictionary.keys():
                        post_id_image_dictionary[post_id].append(url)
                    else:
                        post_id_image_dictionary[post_id] = [url]

                # Add to metadata
                images[url] = {'filename': filename,
                                    'permalink': url,
                                    'description': '<b>Num of Post(s) w/ Image:</b> ' + str(len(data.get('post_ids'))),
                                    'tags': '',
                                    'number_of_posts': 0,
                                    }

        self.dataset.log(f"Metadata for {successful_image_count} images collected from {len(post_id_image_dictionary)} posts")

        # Loop through source file
        posts_with_images = 0
        for post in self.dataset.top_parent().iterate_items(self):
            # Check if post contains one of the downloaded images
            if post['id'] in post_id_image_dictionary.keys():
                posts_with_images += 1
                for img_name in post_id_image_dictionary[post['id']]:
                    image = images[img_name]

                    # Update description
                    image['number_of_posts'] += 1
                    image['description'] += '<br/><br/><b>Post ' + str(image['number_of_posts']) + '</b>'
                    # Order of Description elements
                    ordered_descriptions = ['id', 'timestamp', 'subject', 'body', 'author']
                    for detail in ordered_descriptions:
                        if post.get(detail):
                            image['description'] += '<br/><br/><b>' + detail + ':</b> ' + str(post.get(detail))
                    for key, value in post.items():
                        if key not in ordered_descriptions:
                            image['description'] += '<br/><br/><b>' + key + ':</b> ' + str(value)

                    # Add tags or hashtags
                    if image['tags']:
                        image['tags'] += '|'
                    if 'tags' in post.keys():
                        if type(post['tags']) == list:
                            image['tags'] += '|'.join(post['tags'])
                        else:
                            image['tags'] += '|'.join(post['tags'].split(','))
                    elif 'hashtags' in post.keys():
                        if type(post['hashtags']) == list:
                            image['tags'] += '|'.join(post['hashtags'])
                        else:
                            image['tags'] += '|'.join(post['hashtags'].split(','))

                    # Category could perhaps be a user chosen column...

                    # If images repeat this will overwrite prior value
                    # I really dislike that the download images is not a one to one with posts...
                    if 'timestamp' in post.keys():
                        image['year'] = datetime.strptime(post['timestamp'], "%Y-%m-%d %H:%M:%S").year
        self.dataset.log(f"Image metadata added to {posts_with_images} posts")

        # Get path for metadata file
        metadata_file_path = temp_path.joinpath('metadata.csv')
        # Set fieldnames for metadata file
        fieldnames = ['filename', 'description', 'permalink', 'year', 'tags', 'number_of_posts']

        # Open metadata file and iterate through source file
        with metadata_file_path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            # Finally, write images to metadata.csv
            rows_written = 0
            for image in images.values():
                rows_written += 1
                writer.writerow(image)

        self.dataset.update_status("Metadata.csv created")
        return metadata_file_path if rows_written != 0 else False

    def get_html_page(self, url):
        """
        Returns a html string to redirect to PixPlot.
        """
        return f"<head><meta http-equiv='refresh' charset='utf-8' content='0; URL={url}'></head>"

    def clean_filename(self, s):
        """
        Given a string that points to a filename, return a clean filename

        Copied from PixPlot library to ensure resultant filenames are the same.
        """
        s = unquote(os.path.basename(s))
        invalid_chars = '<>:;,"/\\|?*[]'
        for i in invalid_chars: s = s.replace(i, '')
        return s
