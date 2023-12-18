import datetime
import json
import math
import os
import shutil
import uuid

from PIL import Image, UnidentifiedImageError
from pathlib import Path
from itertools import product

from backend.lib.processor import BasicProcessor

__author__ = "Dale Wahl"
__credits__ = ["Dale Wahl", "Stijn Peeters"]
__maintainer__ = "Dale Wahl"
__email__ = "4cat@oilab.eu"

from common.lib.helpers import get_html_redirect_page, get_software_commit
from common.lib.user_input import UserInput


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
                "tooltip": "Increasing this can easily lead to very long-running processors."
            },
        }
        return options

    def process(self):
        if self.source_dataset.num_rows == 0:
            self.dataset.finish_with_error("No images available to render to visualization.")
            return

        # Unpack the images into a staging area
        self.dataset.update_status("Unzipping images")
        staging_area = self.unpack_archive_contents(self.source_file)

        create_metadata = True if ".metadata.json" in os.listdir(staging_area) else False

        # Collect filenames (skip .json metadata files)
        image_filenames = [filename for filename in os.listdir(staging_area) if
                           filename.split('.')[-1] not in ["json", "log"]]
        if self.parameters.get("amount", 100) != 0:
            image_filenames = image_filenames[:self.parameters.get("amount", 100)]
        total_image_files = len(image_filenames)
        self.dataset.log(f"Total image files: {total_image_files}")

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

        # Results folder
        output_dir = self.dataset.get_results_folder_path()
        output_dir.mkdir(exist_ok=True)

        # Create the manifest
        self.dataset.update_status("Creating manifests for visualization")
        self.cartograph(output_dir,
                        [staging_area.joinpath(image) for image in image_filenames],
                        umap_maps,
                        {"grid": grid_map},
                        clusters=None,
                        root='',
                        atlas_resolution=2048 * 2,
                        cell_height=64 * 2, # min of 64 seems blurry to me
                        thumbnail_size=128, # TODO: changing from 128 breaks the plot; figure out WHY
                        metadata=create_metadata,
                        )

        # Create metadata files
        if create_metadata:
            self.dataset.update_status("Creating metadata files")
            self.create_metadata_files(staging_area, output_dir, self.dataset.top_parent())

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

    @staticmethod
    def cartograph(output_dir, images_paths, umap, position_maps, clusters=None, root="", atlas_resolution=2048,
                   cell_height=64, thumbnail_size=128, metadata=False):
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

        # Update the manifest point sizes
        # TODO: date info to be added to point sizes
        manifest["point_sizes"] = ImagePlotGenerator.specify_point_sizes(len(image_indexes))

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

        return point_sizes

    def create_metadata_files(self, temp_path, output_dir, post_dataset):
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

                    # Category could perhaps be a user chosen column...

                    # If images repeat this will overwrite prior value
                    # I really dislike that the download images is not a one to one with posts...
                    if 'timestamp' in post.keys():
                        image['year'] = datetime.datetime.strptime(post['timestamp'], "%Y-%m-%d %H:%M:%S").year
        self.dataset.log(f"Image metadata added to {posts_with_images} posts")

        # Create metadata files
        metadata_file_path = output_dir.joinpath('data/metadata/file')
        if not os.path.isdir(metadata_file_path):
            os.makedirs(metadata_file_path)

        for image in images.values():
            with open(os.path.join(metadata_file_path, image['filename'] + '.json'), 'w') as file:
                json.dump(image, file)

        self.dataset.update_status("Metadata.csv created")
