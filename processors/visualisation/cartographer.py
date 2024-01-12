import datetime
import operator
import json
import math
import os
import uuid
import zipfile
from dateutil.parser import parse as parse_date

import numpy as np

from collections import defaultdict
from PIL import Image, UnidentifiedImageError
from pathlib import Path
from itertools import product

from backend.lib.processor import BasicProcessor
from common.lib.dataset import DataSet
from common.lib.helpers import get_html_redirect_page
from common.lib.user_input import UserInput

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl", "Stijn Peeters"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"


class ImagePlotGenerator(BasicProcessor):
    """
    Image Plot generator

    Takes an image dataset and creates manifests of point mappings and atlases which can be used by PixPlot's frontend
    to display our mappings.
    """
    type = "custom-image-plot"  # job type ID
    category = "Visual"  # category
    title = "Create Image visualisation"  # title displayed in UI
    description = "Create an explorable map of images using different algorithms to identify similarities."
    extension = "html"  # extension of result file, used internally and in UI

    image_dates = None

    @classmethod
    def is_compatible_with(cls, module=None, user=None):
        """
        Allow processor on image datasets

        :param module: Dataset or processor to determine compatibility with
        """
        return any([module.type.startswith(type_prefixes) for type_prefixes in ["image-downloader", "video-hasher-1"]])

    @classmethod
    def get_options(cls, parent_dataset=None, user=None):
        # Update the amount max and help from config
        options = {
            "amount": {
                "type": UserInput.OPTION_TEXT,
                "help": "No. of images",
                "coerce_type": int,
                "default": 1000,
                "tooltip": "0 will use all images."
            },
        }

        # TODO: enable when I figure out the stupid point sizes UGH
        # # If we have a parent dataset and this dataset has metadata, we can use the metadata to create a category layout
        # if parent_dataset and ImagePlotGenerator.check_for_metadata(parent_dataset.get_results_path()):
        #     parent_columns = parent_dataset.top_parent().get_columns()
        #     if parent_columns:
        #         parent_columns = {c: c for c in sorted(parent_columns)}
        #         parent_columns["None"] = "None"
        #         options["category"] = {
        #             "type": UserInput.OPTION_CHOICE,
        #             "help": "Category column",
        #             "tooltip": "Only one category per image. If left blank, no category layout will be created.",
        #             "options": parent_columns,
        #             "default": "None",
        #     }

        # TODO: enable this when we have a way to map images to network plots
        # if parent_dataset and parent_dataset.is_dataset():
        #     # Get potential mapping datasets
        #     mapping_datasets = ImagePlotGenerator.get_mapping_datasets(parent_dataset)
        #     if mapping_datasets:
        #         mapping_datasets = [DataSet.get_dataset_by_key(key=dataset['key']) for dataset in mapping_datasets]
        #         options["mapping_dataset"] = {
        #             "type": UserInput.OPTION_CHOICE,
        #             "help": "Map images to existing plot",
        #             "options": {dataset.key: dataset.get_label() for dataset in mapping_datasets}, # TODO these labels suck... user defined field for coordinate-map dataset option?
        #             "default": mapping_datasets.pop().key,
        #             "tooltip": "Map images to an existing plot (e.g., from a network). This will override the default map."
        #         }

        return options

    @staticmethod
    def check_for_metadata(path):
        """
        Check if metadata exists for the images in the dataset
        """
        if path.exists() and path.is_file() and path.suffix == ".zip":
            with zipfile.ZipFile(path, "r") as archive_file:
                archive_contents = sorted(archive_file.namelist())
                return True if ".metadata.json" in archive_contents else False
        else:
            return False


    def process(self):
        if self.source_dataset.num_rows == 0:
            self.dataset.finish_with_error("No images available to render to visualization.")
            return
        self.dataset.log(self.parameters)
        # Unpack the images into a staging area
        self.dataset.update_status("Unzipping images")
        staging_area = self.unpack_archive_contents(self.source_file)

        create_metadata = ImagePlotGenerator.check_for_metadata(self.source_file)
        # TODO: images can only have one category, but images can belong to multiple posts!
        category = None if self.parameters.get("category", None) == "None" else self.parameters.get("category", None)

        # Collect filenames (skip .json metadata files)
        image_filenames = [filename for filename in os.listdir(staging_area) if
                           filename.split('.')[-1] not in ["json", "log"]]
        if self.parameters.get("amount", 100) != 0:
            image_filenames = image_filenames[:self.parameters.get("amount", 100)]
        total_image_files = len(image_filenames)
        self.dataset.log(f"Total image files: {total_image_files}")

        # Results folder
        output_dir = self.dataset.get_results_folder_path()
        output_dir.mkdir(exist_ok=True)

        # Create metadata files
        category_layout = None
        if create_metadata:
            self.dataset.update_status("Creating metadata files")
            categories = self.create_metadata_files(staging_area, output_dir, self.dataset.top_parent(), category=category)

            if categories:
                # Create category layout
                categories = [categories.get(filename) for filename in image_filenames]
                self.dataset.update_status(f"Creating categorical layout (num categories: {len(set(categories))}; num images: {len(categories)})")
                category_layout = self.get_categorical_layout(list(set(categories)), categories)

        # Create the grid map
        self.dataset.update_status("Creating grid map")
        # TODO: Order by...?
        grid_map = self.create_grid_map(image_filenames)

        # Create the UMAP map
        # TODO: this. And add options for different types.
        # We'll use the gridmap in place of the UMAP map for now.
        umap_maps = [{
                    "n_neighbors": 3,
                    "min_dist": 1,
                    "positions": grid_map,
                    "positions_jittered": grid_map,
                    }]

        mappings = {"grid": grid_map}
        labels = {}
        if create_metadata and category_layout:
            mappings["categorical"] = dict(zip(image_filenames, category_layout.get("layout")))
            labels["categorical"] = category_layout.get("labels")

        # Create the manifest
        self.dataset.update_status("Creating manifests for visualization")
        self.cartograph(output_dir,
                        [staging_area.joinpath(image) for image in image_filenames],
                        umap_maps,
                        mappings,
                        clusters=None,
                        root='',
                        atlas_resolution=2048 * 2,
                        cell_height=64 * 2, # min of 64 seems blurry to me
                        thumbnail_size=128, # TODO: changing from 128 breaks the plot; figure out WHY
                        metadata=create_metadata,
                        labels=labels,
                        )

        # Results HTML file redirects to output_dir/index.html
        plot_url = ('https://' if self.config.get("flask.https") else 'http://') + self.config.get(
            "flask.server_name") + '/results/' + self.dataset.key + "/plot/"
        html_file = get_html_redirect_page(plot_url)

        # Write HTML file
        with self.dataset.get_results_path().open("w", encoding="utf-8") as output_file:
            output_file.write(html_file)

        # Finish
        self.dataset.update_status("Finished")
        self.dataset.finish(1)

    @staticmethod
    def create_grid_map(list_of_image_filenames):
        """
        Takes a list of image filenames and returns a dictionary mapping each filename to a tuple of x,y floats arranged
        in a grid around the origin (0,0) with a maximum of 1 unit between each image. Filenames are mapped in order of
        the list.

        Format of grid: {"filename": ('float_x', 'float_y'), ...}
        """
        # Size the grid
        num_of_images = len(list_of_image_filenames)
        side_length = math.ceil(math.sqrt(num_of_images))

        # Calculate the coordinates
        x_coordinates = [-1 + (i * (2 / side_length)) for i in range(side_length)]
        y_coordinates = [1 - (i * (2 / side_length)) for i in range(side_length)]
        possible_positions = list(product(x_coordinates, y_coordinates))

        # Sort grid (i.e., start from top left (1,-1) to bottom right (-1,1))
        # Already sorted by x coordinate (from above), now sort by y coordinate
        possible_positions.sort(key=lambda x: x[1], reverse=True)

        # Combine with filenames
        return dict(zip(list_of_image_filenames, possible_positions))

    def cartograph(self, output_dir, images_paths, umap, position_maps, clusters=None, root="", atlas_resolution=2048,
                   cell_height=64, thumbnail_size=128, metadata=False, labels=None):
        """
        Turn image data into a PixPlot-compatible data manifest

        PixPlot requires a number of files to plot images efficiently. It needs
        the positions of each image in the plot, but also a 2048x2048 'atlas'
        containing thumbnails for each image. If there are more images than fit in
        2048x2048, several such atlases are made. A number of JSON files then map
        data between the images, the atlases, and their metadata.

        Given a path to a folder of images, and a dictionary mapping file names to
        (relative) positions, this function will produce all required files for
        PixPlot to plot the images visually.

        This creates a *simplified* manifest and does not cover all of PixPlot's
        native options. It is intended for quick visualisation of large image
        datasets given an arbitrary plotting outcome.

        :param Path output_dir:  Where to create the relevant files.
        :param list[Path] images_paths:  A path to a folder containing images.
        :param list umap:  UMAP positions, each one a dictionary with the keys
        `n_neighbors`, `min_dist`, `positions` and `positions_jittered`.
        :param dict position_maps:  A dictionary, each key being a map name (e.g.
        "umap") and each value being a dictionary of positions, mapping a filename
        to a tuple of x,y floats between -1 and 1. Should NOT include the UMAP
        positions (use `umap` for those).
        :param list clusters:  Clusters of images, each a dictionary with a list of
        `images` (integer indexes), a representative `img` (file name), and a `label`
        :param str root:  Root folder to which the manifest files should refer.
        Defaults to empty, should be the relative path the client-side JavaScript
        looks for.
        :param int atlas_resolution:  Resolution of the (square) atlas textures.
        The default of 2048 seems reasonable.
        :param int cell_height:  Height of thumbnails in atlas textures. Should be an
        integer fraction of the atlas resolution
        :param int thumbnail_size:  Max dimension (width or height, whichever is
        greatest) for the individually generated thumbnails, loaded when zooming in
        """
        # Modified from Stijn https://gist.github.com/stijn-uva/6389a09ef796a1c51bb27c2e75f78a86
        # find eligible image files
        images = []
        sizes = {}
        for image in images_paths:
            if image.suffix.lower() not in (".jpeg", ".jpg", ".png"):
                continue

            images.append(image)
        # pseudo-random ID for plot, used to tie things together
        plot_id = str(uuid.uuid4())

        # prepare folders
        path_thumbnails = output_dir.joinpath("data", "thumbs")
        path_layouts = output_dir.joinpath("data", "layouts")
        path_atlases = output_dir.joinpath("data", "atlases", plot_id)
        path_thumbnails.mkdir(parents=True)
        path_atlases.mkdir(parents=True)
        path_layouts.mkdir(parents=True)

        output_dir.joinpath("data", "imagelists").mkdir(parents=True)
        output_dir.joinpath("data", "hotspots").mkdir(parents=True)

        # prepare manifest - we will add more data as we go
        manifest = {
            "version": "0.0.113",
            "plot_id": plot_id,
            "output_directory": root,
            "layouts": {
                "umap": {
                    "variants": []
                },
                "alphabetic": False,
                "grid": False,
                "categorical": False,
                "date": False,
                "geographic": None,
                "custom": None
            },
            "initial_layout": "umap",
            "point_sizes": {},
            "imagelist": f"{root}/data/imagelists/imagelist-{plot_id}.json",
            "atlas_dir": f"{root}/data/atlases/{plot_id}",
            "metadata": metadata,
            "default_hotspots": f"{root}/data/hotsots/hotspot-{plot_id}.json",
            "custom_hotspots": f"{root}/data/hotspots/user_hotspots.json",
            "gzipped": False,  # TODO Not sure what this option does, but presumably some things can be zipped
            "config": {
                "sizes": {
                    "atlas": atlas_resolution,
                    "cell": cell_height,
                    "lod": thumbnail_size
                }
            },
            "creation_data": datetime.datetime.now().strftime("%d-%B-%Y-%H:%M:%S")
        }

        # create atlases
        imagelist = {
            "cell_sizes": [[]],
            "images": [],
            "atlas": {
                "count": 1,
                "positions": [[]]
            }
        }

        atlas_x = 0
        atlas_y = 0
        atlas_index = 0
        atlas = None

        # keep track of the index of each image, used for efficiently saving the
        # position maps later
        image_indexes = []

        # add images to atlases one by one
        for image in images:
            try:
                original = Image.open(image)
            except (UnidentifiedImageError, TypeError):
                # not a valid image, skip
                continue

            size = (original.width, original.height)
            imagelist["images"].append(image.name)

            # generate individual thumbnail
            # not sure how pixplot handles thumbnails smaller than thumbnail_size
            # just in case, make thumbnail even if original image is smaller
            if size[0] > size[1]:  # width > height
                tsize = (thumbnail_size, (thumbnail_size / size[0]) * size[1])
            else:
                tsize = ((thumbnail_size / size[1]) * size[0], thumbnail_size)

            thumbnail = original.copy()
            thumbnail.thumbnail(tsize)
            thumbnail.save(path_thumbnails.joinpath(image.name))

            # calculate cell size in atlas
            cell_width = (cell_height / size[1]) * size[0]
            if atlas_x + cell_width > atlas_resolution:
                # New row or new atlas
                if atlas_y + cell_height > atlas_resolution:
                    # current atlas is full, save and move to next atlas
                    atlas.save(path_atlases.joinpath(f"atlas-{atlas_index}.jpg"))
                    atlas_index += 1
                    imagelist["atlas"]["count"] += 1
                    imagelist["atlas"]["positions"].append([])
                    imagelist["atlas"]["cell_sizes"].append([])
                    atlas_x = 0
                    atlas_y = 0
                    atlas = None
                else:
                    # move to next row
                    atlas_x = 0
                    atlas_y += cell_height

            if atlas is None:
                # initialise a new atlas
                atlas = Image.new("RGB", (atlas_resolution, atlas_resolution))

            # copy cell to atlas
            cell = original.copy()
            cell.thumbnail((cell_width, cell_height))
            atlas.paste(cell, (atlas_x, atlas_y))

            # save positions to imagelist
            imagelist["atlas"]["positions"][atlas_index].append((atlas_x, atlas_y))
            imagelist["cell_sizes"][atlas_index].append(tsize)
            image_indexes.append(image.name)

            # Prepare for next image by increasing the atlas_x by width of the cell
            atlas_x = math.ceil(atlas_x + cell_width)

        # Get date layout if possible
        date_columns = None
        date_labels = None
        if metadata and self.image_dates is not None:
            image_filenames = [image.name for image in images]
            date_layout = self.get_date_layout(image_filenames)
            if date_layout:
                position_maps["date"] = dict(zip(image_filenames, date_layout.get("layout", {})))
                labels["date"] = date_layout.get("labels", {})

            date_columns = date_layout.get('labels', {}).get('cols', None)
            date_labels = len(set(date_layout.get('labels', {}).get("labels", [])))

        # Create point_sizes for starting atlas image size and text size (text come from date layout)
        # TODO would be nice to have some concept of date_columns for categorical layout in case we somehow don't have a date layout
        manifest["point_sizes"] = ImagePlotGenerator.specify_point_sizes(len(image_indexes), date_columns=date_columns, date_labels=date_labels, umap=False)

        # done with the atlases, save final one too
        if not atlas:
            raise RuntimeError("Image folder contained no valid images")
        atlas.save(path_atlases.joinpath(f"atlas-{atlas_index}.jpg"))

        # moving on to the positioning in the plot...
        allowed_layouts = ("umap", "alphabetic", "grid", "categorical", "date", "geographic", "custom")
        layouts = {}
        for layout, positions in position_maps.items():
            if layout not in allowed_layouts:
                raise ValueError(f"Layout must be one of {''.join(allowed_layouts)}, {layout} given")

            ordered_positions = []
            for imagename in imagelist["images"]:
                if imagename not in positions:
                    raise ValueError(f"Position missing for image {imagename} in layout {layout}")
                if type(positions[imagename]) not in (tuple, list):
                    raise TypeError(
                        f"Position for image {imagename} in layout {layout} must be tuple or list, {repr(positions[imagename])} given")

                ordered_positions.append(positions[imagename])

            layouts[layout] = ordered_positions

        # and finally, clusters
        hotspots = []
        if not clusters:
            clusters = []

        required_fields = {"images", "img", "label"}
        for cluster in clusters:
            # some thorough checking here because this is easy to mess up
            if required_fields & set(cluster.keys()) != required_fields:
                raise ValueError("Clusters must have images, img, and label keys")

            if type(cluster["images"]) not in (tuple, list):
                raise ValueError("Cluster images must be a tuple or list")

            if set([type(item) for item in cluster["images"]]) != {int} or min(cluster["images"]) < 0 or max(
                    cluster["images"]) >= len(imagelist["images"]):
                raise ValueError(
                    "Cluster images list must contain only integers between 0 and the number of images in the dataset")

            if cluster["img"] not in imagelist["images"]:
                raise ValueError(f"Cluster thumbnail image {cluster['img']} not in image list")

            # ok, hotspot ready
            hotspots.append({
                "images": cluster["images"],
                "img": cluster["img"],
                "layout": "inception_vectors",  # seems unused
                "label": cluster["label"]
            })

        for layout, positions in layouts.items():
            if not positions or layout.startswith("umap"):
                # umap is a special case
                continue

            layout_path = path_layouts.joinpath(f"{layout}-{plot_id}.json")
            with layout_path.open("w") as outfile:
                json.dump(positions, outfile)

            manifest["layouts"][layout] = {
                "layout": f"{root}/data/layouts/{layout}-{plot_id}.json"
            }

        if labels:
            for layout, layout_labels in labels.items():
                if layout not in manifest["layouts"]:
                    raise ValueError(f"Labels for layout {layout} given, but layout not found in position mappings")
                self.dataset.log(f"Writing labels for {layout} layout")
                label_path = path_layouts.joinpath(f"{layout}-labels-{plot_id}.json")
                with label_path.open("w") as outfile:
                    json.dump(layout_labels, outfile)

                manifest["layouts"][layout]["labels"] = f"{root}/data/layouts/{layout}-labels-{plot_id}.json"

        # write UMAP-generated positions
        for i, variant in enumerate(umap):
            manifest_variant = {
                "n_neighbors": variant["n_neighbors"],
                "min_dist": variant["min_dist"],
            }

            with path_layouts.joinpath(f"umap-{plot_id}.json").open("w") as outfile:
                ordered_positions = []
                for imagename in imagelist["images"]:
                    if imagename not in variant["positions"]:
                        raise ValueError(f"Position missing for image {imagename} in umap variant {i}")
                    if type(variant["positions"][imagename]) not in (tuple, list):
                        raise TypeError(
                            f"Position for image {imagename} in umap variant {i} must be tuple or list, {repr(variant['positions'][imagename])} given")

                    ordered_positions.append(variant["positions"][imagename])
                json.dump(ordered_positions, outfile)
                manifest_variant["layout"] = f"{root}/data/layouts/umap-{plot_id}.json"
                # del variant["positions"]

            with path_layouts.joinpath(f"umap-jittered-{plot_id}.json").open("w") as outfile:
                ordered_positions = []
                for imagename in imagelist["images"]:
                    if imagename not in variant["positions_jittered"]:
                        raise ValueError(f"Position missing for image {imagename} in umap variant {i}")
                    if type(variant["positions_jittered"][imagename]) not in (tuple, list):
                        raise TypeError(
                            f"Position for image {imagename} in umap variant {i} must be tuple or list, {repr(variant['positions_jittered'][imagename])} given")

                    ordered_positions.append(variant["positions_jittered"][imagename])
                json.dump(ordered_positions, outfile)
                manifest_variant["jittered"] = f"{root}/data/layouts/umap-jittered-{plot_id}.json"
                # del variant["positions_jittered"]

            manifest["layouts"]["umap"]["variants"].append(manifest_variant)

        # write the JSONs
        with output_dir.joinpath(f"data/hotspots/hotspot-{plot_id}.json").open("w") as outfile:
            json.dump(hotspots, outfile)

        with output_dir.joinpath(f"data/imagelists/imagelist-{plot_id}.json").open("w") as outfile:
            json.dump(imagelist, outfile)

        with output_dir.joinpath(f"data/manifest.json").open("w") as outfile:
            json.dump(manifest, outfile)

    @staticmethod
    def specify_point_sizes(num_of_images, date_columns=None, date_labels=None, umap=False):
        """
        Specify point size scalars. These are used to scale the thumbnail sizes based on the number of images.

        Adapted from here:
        https://github.com/YaleDHLab/pix-plot/blob/84afbd098f24c5a3ec41219fa849d3eb7b3dc57f/pixplot/pixplot.py#L422

        If there is date information, the point size for the date layout is scaled by the number of date columns (+ 1)
        times the number of date labels.

        :param num_of_images: Number of images in the dataset
        :param date_columns: Number of date columns in the dataset
        :param date_labels: Number of date labels in the dataset
        :param umap: Whether or not umap was used for initial and scatter layouts
        """
        grid = 1 / math.ceil(num_of_images ** (1 / 2))
        # TODO: These seem "fluffy". Can we do better?
        point_sizes = {
            'min': 0,
            'grid': grid,
            "max": grid * 1.5,
            "scatter": grid * .2 if umap else grid,
            "initial": grid * .2 if umap else grid,
            "categorical": grid * .6,
            "geographic": grid * .025,
        }
        # fetch the date distribution data for point sizing
        if date_columns is not None and date_labels is not None:
            # date: number of columns (+ 1) times the number of date labels
            point_sizes['date'] = 1 / ((date_columns + 1) * date_labels)

            point_sizes['cat_text'] = point_sizes['date'] * 0.5

        return point_sizes

    def create_metadata_files(self, temp_path, output_dir, post_dataset, category=None):
        """
        Creates a metadata file folder w/ json files for each image.

        JSON format:
        {
         "": "1", # Order of images
        "filename": "B76NjK3p0aD_2.jpg", # filanem
        "category": "wakeupsheeple", # category if used; for categorical layout
        "tags": [], # tags if used; for selector
        "description": "", # displays in the info panel
        "permalink": "https://www.instagram.com/p/B76NjK3p0aD", # link to original post; TODO: unsure where this is used
        "year": "2001", # for date layout
        }

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

                for post_id in data.get('post_ids'):
                    # Add key to post ID dictionary
                    if post_id in post_id_image_dictionary.keys():
                        post_id_image_dictionary[post_id].append(url)
                    else:
                        post_id_image_dictionary[post_id] = [url]

                # Add to metadata
                images[url] = {
                    '': successful_image_count,
                    'filename': data.get('filename'),
                    'permalink': url,
                    'description': '<b>Num of Post(s) w/ Image:</b> ' + str(len(data.get('post_ids'))),
                    'tags': [],
                    'number_of_posts': 0,
                    }
                if category:
                    # multiple posts means multiple possible categories...
                    images[url]['category'] = []

        self.dataset.log(f"Metadata for {successful_image_count} images collected from {len(post_id_image_dictionary)} posts")

        # Loop through source file
        posts_with_images = 0
        for post in post_dataset.iterate_items(self):
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

                        # Add timestamps to image_dates
                        if detail == 'timestamp':
                            if not self.image_dates:
                                self.image_dates = {}
                            if image.get("filename") not in self.image_dates.keys():
                                self.image_dates[image.get("filename")] = parse_date(post.get(detail))
                            else:
                                # Use earliest date
                                self.image_dates[image.get("filename")] = min(parse_date(post.get(detail)), self.image_dates[image.get("filename")])

                    for key, value in post.items():
                        if key not in ordered_descriptions:
                            image['description'] += '<br/><br/><b>' + key + ':</b> ' + str(value)

                    # Add tags or hashtags
                    if 'tags' in post.keys():
                        if type(post['tags']) == list:
                            image['tags'] += post['tags']
                        else:
                            image['tags'] += post['tags'].split(',')
                    elif 'hashtags' in post.keys():
                        if type(post['hashtags']) == list:
                            image['tags'] += post['hashtags']
                        else:
                            image['tags'] += post['hashtags'].split(',')

                    # If images repeat this will overwrite prior value
                    # I really dislike that the download images is not a one to one with posts...
                    if 'timestamp' in post.keys():
                        image['year'] = datetime.datetime.strptime(post['timestamp'], "%Y-%m-%d %H:%M:%S").year

                    if category:
                        image['category'] += [post.get(category, "None")]

        self.dataset.log(f"Image metadata added to {posts_with_images} posts")

        # The Image Plot only supports one category per image, so we combine all categories into one string
        if category:
            # Remove duplicates from categories & combine into one string
            for image in images.values():
                image['category'] = ",".join(list(set(image['category'])))

        # Create metadata files
        metadata_file_path = output_dir.joinpath('data/metadata/file')
        if not os.path.isdir(metadata_file_path):
            os.makedirs(metadata_file_path)

        for image in images.values():
            with open(os.path.join(metadata_file_path, image['filename'] + '.json'), 'w') as file:
                json.dump(image, file)

        self.dataset.update_status("Metadata.csv created")

        # Return categories for categorical layout
        if category:
            return {image['filename']: image['category'] for image in images.values()}
        else:
            return False

    @staticmethod
    def get_mapping_datasets(parent_dataset):
        """
        The cartographer can collect mappings from other datasets from the same datasource top level dataset.

        :param DataSet parent_dataset: The parent dataset of the current dataset
        """
        top_dataset = parent_dataset.top_parent()
        return [dataset for dataset in top_dataset.get_all_children(instantiate_datasets=False) if dataset.get('type') == "coordinate-map"]


# Adapted from YaleDHLab's PixPlot here:
# https://github.com/YaleDHLab/pix-plot/blob/84afbd098f24c5a3ec41219fa849d3eb7b3dc57f/pixplot/pixplot.py#L975

    def get_categorical_layout(self, categories, images_to_category, null_category='Other', margin=2, **kwargs):
        """
        Return a numpy array with shape (n_points, 2) with the point
        positions of observations in box regions determined by
        each point's category metadata attribute (if applicable)

        :param [str] categories: list of categories
        :param [str] images_to_category: ordered list of image categories ['image_1_category_name', 'image_2_category_name', ...]
        """
        # if not kwargs.get('metadata', False): return False
        # # determine the out path and return from cache if possible
        # out_path = get_path('layouts', 'categorical', **kwargs)
        # labels_out_path = get_path('layouts', 'categorical-labels', **kwargs)


        # accumulate d[category] = [indices of points with category]
        # categories = [i.get('category', None) for i in kwargs['metadata']] # TODO List of categories?
        if not any(categories) or len(set(categories) - set([None])) == 1: return False
        d = defaultdict(list)
        for idx, i in enumerate(images_to_category): d[i].append(idx)
        # store the number of observations in each group
        keys_and_counts = [{'key': i, 'count': len(d[i])} for i in d]
        keys_and_counts.sort(key=operator.itemgetter('count'), reverse=True)
        # get the box layout then subdivide into discrete points
        boxes = get_categorical_boxes([i['count'] for i in keys_and_counts], margin=margin)
        points = get_categorical_points(boxes)
        # sort the points into the order of the observations in the metadata
        counts = {i['key']: 0 for i in keys_and_counts}
        offsets = {i['key']: 0 for i in keys_and_counts}
        for idx, i in enumerate(keys_and_counts):
            offsets[i['key']] += sum([j['count'] for j in keys_and_counts[:idx]])
        sorted_points = []
        # for idx, i in enumerate(stream_images(**kwargs)): # TODO Pass images in order w/ metadata?
            # category = i.metadata.get('category', null_category)
        for idx, category in enumerate(images_to_category):
            if category is None:
                category = null_category
            sorted_points.append(points[ offsets[category] + counts[category] ])
            counts[category] += 1
        sorted_points = np.array(sorted_points)
        # add to the sorted points the anchors for the text labels for each group
        text_anchors = np.array([[i.x, i.y-margin/2] for i in boxes])
        # add the anchors to the points - these will be removed after the points are projected
        sorted_points = np.vstack([sorted_points, text_anchors])
        # scale -1:1 using the largest axis as the scaling metric
        _max = np.max(sorted_points)
        for i in range(2):
            _min = np.min(sorted_points[:,i])
            sorted_points[:,i] -= _min
            sorted_points[:,i] /= (_max-_min)
            sorted_points[:,i] -= np.max(sorted_points[:,i])/2
            sorted_points[:,i] *= 2
        # separate out the sorted points and text positions
        text_anchors = sorted_points[-len(text_anchors):]
        sorted_points = sorted_points[:-len(text_anchors)]
        z = round_floats(sorted_points.tolist())
        # Structure for manifest
        return {
            # 'layout': write_json(out_path, z, **kwargs), # TODO: we are writing this elsewhere in cartographer.py
            # 'labels': write_json(labels_out_path, { # TODO: Ditto... well not yet, but ought we to be? other layouts have labels too
            #         'positions': round_floats(text_anchors.tolist()),
            #         'labels': [i['key'] for i in keys_and_counts],
            #     }, **kwargs)
            'layout': z,
            'labels': {
              'positions': round_floats(text_anchors.tolist()),
              'labels': [i['key'] for i in keys_and_counts],
            }
        }
    def get_date_layout(self, image_filenames, cols=3, bin_units='years'):
      '''
      Get the x,y positions of input images based on their dates
      @param int cols: the number of columns to plot for each bar
      @param str bin_units: the temporal units to use when creating bins
      '''
      print('Creating date layout with {} columns'.format(cols))
      datestrings = [self.image_dates.get(image, 'no_date') for image in image_filenames]
      dates = [datestring_to_date(i) for i in datestrings]
      rounded_dates = [round_date(i, bin_units) for i in dates]
      # create d[formatted_date] = [indices into datestrings of dates that round to formatted_date]
      d = defaultdict(list)
      for idx, i in enumerate(rounded_dates):
        d[i].append(idx)
      # determine the number of distinct grid positions in the x and y axes
      n_coords_x = (cols+1)*len(d)
      n_coords_y = 1 + max([len(d[i]) for i in d]) // cols
      if n_coords_y > n_coords_x: return self.get_date_layout(image_filenames, cols=int(cols*2), bin_units=bin_units)
      # create a mesh of grid positions in clip space -1:1 given the time distribution
      grid_x = (np.arange(0,n_coords_x)/(n_coords_x-1))*2
      grid_y = (np.arange(0,n_coords_y)/(n_coords_x-1))*2
      # divide each grid axis by half its max length to center at the origin 0,0
      grid_x = grid_x - np.max(grid_x)/2.0
      grid_y = grid_y - np.max(grid_y)/2.0
      # make dates increase from left to right by sorting keys of d
      d_keys = np.array(list(d.keys()))
      seconds = np.array([date_to_seconds(dates[ d[i][0] ]) for i in d_keys])
      d_keys = d_keys[np.argsort(seconds)]
      # determine which images will fill which units of the grid established above
      coords = np.zeros((len(datestrings), 2)) # 2D array with x, y clip-space coords of each date
      for jdx, j in enumerate(d_keys):
        for kdx, k in enumerate(d[j]):
          x = jdx*(cols+1) + (kdx%cols)
          y = kdx // cols
          coords[k] = [grid_x[x], grid_y[y]]
      # find the positions of labels
      label_positions = np.array([ [ grid_x[i*(cols+1)], grid_y[0] ] for i in range(len(d)) ])
      # move the labels down in the y dimension by a grid unit
      dx = (grid_x[1]-grid_x[0]) # size of a single cell
      label_positions[:,1] = label_positions[:,1] - dx
      # quantize the label positions and label positions
      image_positions = round_floats(coords)
      label_positions = round_floats(label_positions.tolist())
      # write and return the paths to the date based layout
      return {
        'layout': image_positions,
        'labels': {
          'positions': label_positions,
          'labels': d_keys.tolist(),
          'cols': cols,
        }
      }


def get_categorical_boxes(group_counts, margin=2):
    """
    @arg [int] group_counts: counts of the number of images in each
    distinct level within the metadata's caetgories
    @kwarg int margin: space between boxes in the 2D layout
    @returns [Box] an array of Box() objects; one per level in `group_counts`
    """
    group_counts = sorted(group_counts, reverse=True)
    boxes = []
    for i in group_counts:
        w = h = math.ceil(i**(1/2))
        boxes.append(Box(i, w, h, None, None))
    # find the position along x axis where we want to create a break
    wrap = math.floor(sum([i.cells for i in boxes])**(1/2)) - (2 * margin)
    # find the valid positions on the y axis
    y = margin
    y_spots = []
    for i in boxes:
        if (y + i.h + margin) <= wrap:
            y_spots.append(y)
            y += i.h + margin
        else:
            y_spots.append(y)
            break
    # get a list of lists where sublists contain elements at the same y position
    y_spot_index = 0
    for i in boxes:
        # find the y position
        y = y_spots[y_spot_index]
        # find members with this y position
        row_members = [j.x + j.w for j in boxes if j.y == y]
        # assign the y position
        i.y = y
        y_spot_index = (y_spot_index + 1) % len(y_spots)
        # assign the x position
        i.x = max(row_members) + margin if row_members else margin
    return boxes

def get_categorical_points(arr, unit_size=None):
    """
    Given an array of Box() objects, return a 2D distribution with shape (n_cells, 2)
    """
    points_arr = []
    for i in arr:
        area = i.w*i.h
        per_unit = (area / i.cells)**(1/2)
        x_units = math.ceil(i.w / per_unit)
        y_units = math.ceil(i.h / per_unit)
        if not unit_size: unit_size = min(i.w/x_units, i.h/y_units)
        for j in range(i.cells):
            x = j%x_units
            y = j//x_units
            points_arr.append([
                    i.x+x*unit_size,
                    i.y+y*unit_size,
            ])
    return np.array(points_arr)

def round_floats(obj, digits=5):
  """
  Return 2D array obj with rounded float precision
  """
  return [[round(float(j), digits) for j in i] for i in obj]

class Box:
    """
    Store the width, height, and x, y coords of a box
    """
    def __init__(self, *args):
        self.cells = args[0]
        self.w = args[1]
        self.h = args[2]
        self.x = None if len(args) < 4 else args[3]
        self.y = None if len(args) < 5 else args[4]

##
# Date Layout
##


def datestring_to_date(datestring):
  '''
  Given a string representing a date return a datetime object
  '''
  try:
    return parse_date(str(datestring), fuzzy=True, default=datetime.datetime(9999, 1, 1))
  except Exception as exc:
    print('Could not parse datestring {}'.format(datestring))
    return datestring


def date_to_seconds(date):
  '''
  Given a datetime object return an integer representation for that datetime
  '''
  if isinstance(date, datetime.datetime):
    return (date - datetime.datetime.today()).total_seconds()
  else:
    return - float('inf')


def round_date(date, unit):
  '''
  Return `date` truncated to the temporal unit specified in `units`
  '''
  if not isinstance(date, datetime.datetime): return 'no_date'
  formatted = date.strftime('%d %B %Y -- %X')
  if unit in set(['seconds', 'minutes', 'hours']):
    date = formatted.split('--')[1].strip()
    if unit == 'seconds': date = date
    elif unit == 'minutes': date = ':'.join(date.split(':')[:-1]) + ':00'
    elif unit == 'hours': date = date.split(':')[0] + ':00:00'
  elif unit in set(['days', 'months', 'years', 'decades', 'centuries']):
    date = formatted.split('--')[0].strip()
    if unit == 'days': date = date
    elif unit == 'months': date = ' '.join(date.split()[1:])
    elif unit == 'years': date = date.split()[-1]
    elif unit == 'decades': date = str(int(date.split()[-1])//10) + '0'
    elif unit == 'centuries': date = str(int(date.split()[-1])//100) + '00'
  return date
