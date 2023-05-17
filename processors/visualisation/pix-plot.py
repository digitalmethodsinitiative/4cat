"""
Create an PixPlot of downloaded images

Use http://host.docker.internal:4000 to connect to docker hosted PixPlot on
same server (assuming that container is exposing port 4000).
"""
import shutil
from json import JSONDecodeError

import requests
import time
import json
from datetime import datetime
import csv
import os
from urllib.parse import unquote
from werkzeug.utils import secure_filename

from common.config_manager import config
from common.lib.helpers import UserInput, convert_to_int
from backend.abstract.processor import BasicProcessor

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
        # If you host a version of https://github.com/digitalmethodsinitiative/dmi_pix_plot, you can use a processor to publish
        # downloaded images into a PixPlot there
        'pix-plot.PIXPLOT_SERVER': {
            'type': UserInput.OPTION_TEXT,
            'default': "",
            'help': 'PixPlot Server Address/URL',
            'tooltip': "",
        },
    }

    options = {
        "amount": {
            "type": UserInput.OPTION_TEXT,
            "help": "No. of images (max 1000)",
            "default": 1000,
            "min": 0,
            "max": 10000,
            "tooltip": "'0' uses as many images as available in the source image archive (up to 10000)"
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

    @classmethod
    def is_compatible_with(cls, module=None):
        """
        Allow processor on token sets;
        Checks if pix-plot.PIXPLOT_SERVER set

        :param module: Dataset or processor to determine compatibility with
        """
        return module.type.startswith("image-downloader") and config.get('pix-plot.PIXPLOT_SERVER')

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

        # 0 = use as many images as in the archive, up to the max
        max_images = convert_to_int(self.parameters.get("amount"), 100)
        if max_images == 0:
            max_images = self.get_options()["amount"]["max"]

		# Get labels to send PixPlot server
		date = datetime.now().strftime("%Y-%m-%d-%H%M%S")
		top_dataset = self.dataset.top_parent()
		label_formated = ''.join(e if e.isalnum() else '_' for e in top_dataset.get_label())
		image_label = datetime.fromtimestamp(self.source_dataset.timestamp).strftime("%Y-%m-%d-%H%M%S") + '-' + label_formated + '-' + str(top_dataset.key)
		plot_label = date + '-' + label_formated + '-' + str(self.dataset.key)
		pixplot_server = config.get('pix-plot.PIXPLOT_SERVER', user=self.owner).rstrip("/")

        # Folder name is PixPlot identifier and set at dataset key
        data = {'folder_name': image_label}

		# Check if images have already been sent
		filename_url = pixplot_server + '/api/list_filenames?folder_name=' + image_label
		filename_response = requests.get(filename_url, timeout=30)

        # Check if 4CAT has access to this PixPlot server
        if filename_response.status_code == 403:
            self.dataset.update_status("403: 4CAT does not have permission to use this PixPlot server", is_final=True)
            self.dataset.finish(0)
            return

        uploaded_files = filename_response.json().get('filenames', [])
        if len(uploaded_files) > 0:
            self.dataset.update_status("Found %i images previously uploaded" % (len(uploaded_files)))

        # Images
        # Unpack the images into a staging_area
        self.dataset.update_status("Unzipping images")
        staging_area = self.unpack_archive_contents(self.source_file)
        self.log.info('PixPlot image staging area created: ' + str(staging_area))
        filenames = os.listdir(staging_area)

        # Compare photos with upload images
        filenames = [filename for filename in filenames if
                     filename not in uploaded_files + ['.metadata.json', 'metadata.csv']]
        total_images = len(filenames) + len(uploaded_files)

        # Check to ensure enough photos will be uploaded to create a PixPlot
        if total_images < self.min_photos_needed:
            self.dataset.update_status(
                "Minimum of %i photos needed for a PixPlot to be created" % self.min_photos_needed, is_final=True)
            self.dataset.finish(0)
            return

		# Gather metadata
		self.dataset.update_status("Collecting metadata")
		metadata_file_path = self.format_metadata(staging_area)
		# Metadata
		upload_url = pixplot_server + '/api/send_metadata'
		metadata_response = requests.post(upload_url, files={'metadata': open(metadata_file_path, 'rb')}, data=data, timeout=120)

		# Now send photos to PixPlot
		self.dataset.update_status("Uploading images to PixPlot")
		# Configure upload photo url
		upload_url = pixplot_server + '/api/send_photo'
		images_uploaded = 0
		estimated_num_images = len(filenames)
		self.dataset.update_status("Uploading %i images" % (estimated_num_images))
		# Begin looping through photos
		for i, filename in enumerate(filenames):
			if self.interrupted:
				raise ProcessorInterruptedException("Interrupted while downloading images.")

            if i > max_images:
                break
            with open(os.path.join(staging_area, filename), 'rb') as image:
                response = requests.post(upload_url, files={'image': image}, data=data, timeout=120)

            if response.status_code == 200:
                image_response = response
                images_uploaded += 1
                if images_uploaded % 100 == 0:
                    self.dataset.update_status("Images uploaded: %i of %i" % (i, estimated_num_images))
            else:
                self.dataset.update_status(
                    "Error with image %s: %i - %s" % (filename, response.status_code, response.reason))

            self.dataset.update_progress(i / self.source_dataset.num_rows)

		# Request PixPlot server create PixPlot
		self.dataset.update_status("Sending create PixPlot request")
		create_plot_url = pixplot_server + '/api/pixplot'
		# Gather info from PixPlot server response
		create_pixplot_post_info = metadata_response.json()['create_pixplot_post_info']
		# Create json package for creation request
		json_data = {'args': ['--images', create_pixplot_post_info.get('images_folder') + "/*",
							  '--out_dir', create_pixplot_post_info.get('plot_folder_root') + '/' + plot_label,
							  '--metadata', create_pixplot_post_info.get('metadata_filepath')]}

        # Additional options for PixPlot
        cell_size = self.parameters.get('image_size')
        n_neighbors = self.parameters.get('n_neighbors')
        min_dist = self.parameters.get('min_dist')
        json_data['args'] += ['--cell_size', str(cell_size), '--n_neighbors', str(n_neighbors), '--min_dist',
                              str(min_dist)]

        # Increase timeout (default is 3600 seconds)
        json_data['timeout'] = 21600

        # Send; receives response that process has started
        resp = requests.post(create_plot_url, json=json_data, timeout=30)
        if resp.status_code == 202:
            # new request
            new_request = True
            results_url = config.get('pix-plot.PIXPLOT_SERVER').rstrip('/') + '/api/pixplot?key=' + resp.json()['key']
        else:
            try:
                resp_json = resp.json()
            except JSONDecodeError as e:
                # Unexpected Error
                self.log.error('PixPlot create response: ' + str(resp.status_code) + ': ' + str(resp.text))
                if staging_area:
                    shutil.rmtree(staging_area)
                raise RuntimeError("PixPlot unable to process request")

		if resp.status_code == 202:
			# new request
			new_request = True
			results_url = pixplot_server + '/api/pixplot?key=' + resp.json()['key']
		elif 'already exists' in resp.json()['error']:
			# repeat request
			new_request = False
		else:
			self.log.error('PixPlot create response: ' + str(resp.status_code) + ': ' + str(resp.text))
			if staging_area:
				shutil.rmtree(staging_area)
			raise RuntimeError("PixPlot unable to process request")

        # Wait for PixPlot to complete
        self.dataset.update_status("PixPlot generating results")
        start_time = time.time()
        while new_request:
            time.sleep(1)
            # If interrupted is called, attempt to finish dataset while PixPlot server still running
            if self.interrupted:
                break

			# Send request to check status every 60 seconds
			if int(time.time() - start_time) % 60 == 0:
				result = requests.get(results_url, timeout=30)
				self.log.debug(str(result.json()))
				if 'status' in result.json().keys() and result.json()['status'] == 'running':
					# Still running
					continue
				elif 'report' in result.json().keys() and result.json()['report'][-6:-1] == 'Done!':
					# Complete without error
					self.dataset.update_status("PixPlot Completed!")
					self.log.info('PixPlot saved on : ' + pixplot_server)
					break
				else:
					# Something botched
					self.dataset.finish_with_error("PixPlot Error on creation")
					self.log.error("PixPlot Error: " + str(result.json()))
					return

		# Create HTML file
		plot_url = pixplot_server + '/plots/' + plot_label + '/index.html'
		html_file = self.get_html_page(plot_url)

        plot_url = pix_plot_server + '/plots/' + plot_label + '/index.html'
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
        # Get path for metadata file
        metadata_file_path = temp_path.joinpath('metadata.csv')
        # Set fieldnames for metadata file
        fieldnames = ['filename', 'description', 'permalink', 'year', 'tags', 'number_of_posts']

        # Open metadata file and iterate through source file
        with metadata_file_path.open("w", encoding="utf-8", newline="") as output:
            # Our to-be metadata
            images = {}

            # Reformat image_data to access by filename and begin metadata
            post_id_image_dictionary = {}
            for url, data in image_data.items():

                # Check if image successfully downloaded for image
                if data.get('success'):
                    ids = data.get('post_ids')
                    # dmi_pix_plot API uses sercure_filename while pixplot.py (in PixPlot library) uses clean_filename
                    # Ensure our metadata filenames match results
                    filename = self.clean_filename(secure_filename(data.get('filename')))
                    for post_id in ids:
                        # Add to key
                        if post_id in post_id_image_dictionary.keys():
                            post_id_image_dictionary[post_id].append(filename)
                        else:
                            post_id_image_dictionary[post_id] = [filename]

                    # Add to metadata
                    images[filename] = {'filename': filename,
                                        'permalink': url,
                                        'description': '<b>Num of Post(s) w/ Image:</b> ' + str(len(ids)),
                                        'tags': '',
                                        'number_of_posts': 0,
                                        }

            self.dataset.log(f"Metadata for {len(images)} images collected from {len(post_id_image_dictionary)} posts")
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

                        # PixPlot has a field limit of 131072
                        # TODO: PixPlot (dmi version) has been updated and this likely is no longer needed
                        # test first as displaying long descriptions still may have issues
                        image['description'] = image['description'][:131072]

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

                        # Category could perhaps be a user inputed column...

                        # If images repeat this will overwrite prior value
                        # I really dislike that the download images is not a one to one with posts...
                        if 'timestamp' in post.keys():
                            image['year'] = datetime.strptime(post['timestamp'], "%Y-%m-%d %H:%M:%S").year
            self.dataset.log(f"Image metadata added to {posts_with_images} posts")

            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()

            # Finally, write images to metadata.csv
            rows_written = 0
            for image in images:
                rows_written += 1
                writer.writerow(images[image])

        self.dataset.update_status("Metadata.csv created")
        return metadata_file_path if rows_written != 0 else False

    def get_html_page(self, url):
        """
		Returns a html string to redirect to PixPlot.
		"""
        return f"<head><meta http-equiv='refresh' charset='utf-8' content='0; URL={url}'></head>"

    def clean_filename(self, s):
        '''
		Given a string that points to a filename, return a clean filename

		Copied from PixPlot library to ensure resultant filenames are the same.
		'''
        s = unquote(os.path.basename(s))
        invalid_chars = '<>:;,"/\\|?*[]'
        for i in invalid_chars: s = s.replace(i, '')
        return s
