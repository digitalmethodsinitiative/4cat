from setuptools import setup
import os

with open("README.md", 'r') as readmefile:
	readme = readmefile.read()

with open("VERSION") as versionfile:
	version = versionfile.readline().strip()

core_packages = {
	# 4CAT core dependencies
	# (backend, frontend, etc)
	"bcrypt~=3.2.0",
	"Flask~=3.0",
	"Flask_Limiter[memcached]",
	"Flask_Login~=0.6",
	"html2text==2020.*",
	"ImageHash>4.2.0",
	"json_stream",
	"langchain_core",
	"langchain_community",
	"langchain_anthropic",
	"langchain_google_genai",
	"langchain_ollama",
	"langchain_openai",
	"langchain_mistralai",
	"markdown2==2.4.2",
	"oslex",
	"packaging",
	"psutil~=5.0",
	"Pillow>=10.3",  
	"pydantic",
	"pymemcache",
	"PyMySQL~=1.0",
	"psycopg2~=2.9.0",
	"pytest",
	"pytest-dependency",
	"requests~=2.27",
	"requests_futures",
	"ruff",
	"svgwrite~=1.4.0",
	"ural~=1.3",
	"Werkzeug"
}

processor_packages = {
	# 4CAT processor dependencies
	"anytree~=2.8.0",  # word-trees
	"atproto>=0.0.58",  # search_bsky
	"beautifulsoup4",  # url_titles, search_tiktok_urls, search_douban
	"clarifai-grpc~=9.0",  # clarifai_api
	"cssselect~=1.1.0",  # download_images_4chan, wikipedia_network
	"emoji>=2.12.1",  # rank_attribute
	"gensim>=4.3.3, <4.4.0",  # similar_words, tf_idf, generate_embeddings, histwords
	"google_api_python_client",  # perspective, youtube_metadata
	"jieba",  # word-trees, tokenise
	"jsonschema",  # llm_prompter
	"lxml",  # dowload_images_4chan, wikipedia_network, url_titles
	"nltk~=3.9.1",  # similar-words, word-trees, collocations, split_sentences, tokenise
	"networkx~=2.8.0",  # networks/*
	"numpy>=1.19.2",  # image_wall, histwords, video_hasher, hash_similarity_network, aggregate_stats, tf_idf
	"pandas",  # youtube_imagewall, tf_idf
	"pyahocorasick~=1.4.0",  # tokenise
	"PyTumblr==0.1.0",  # search_tumblr
	"razdel~=0.5",  # tokenise
	"scenedetect[opencv]",  # video_scene_identifier
	"scikit-learn",  # image_wall, histwords, tf_idf, topic_modeling, classification_evaluation, confusion_matrix
	"Telethon~=1.36.0",  # search_telegram, download-telegram-videos, download-telegram-images
	"unidecode~=1.3",  # accent_fold
	"wordcloud~=1.8",  # word-cloud
	# The https://github.com/akamhy/videohash is not being maintained anymore; these are two patches
	"imagedominantcolor @ git+https://github.com/dale-wahl/imagedominantcolor.git@pillow10",
	"videohash @ git+https://github.com/dale-wahl/videohash@main",  # video_hasher
	"vk_api",  # search_vk
	"yt-dlp"  # download_videos
}

packages = core_packages | processor_packages

# Check for extension packages
if os.path.isdir("config/extensions"):
	extension_packages = set()
	for root, dirs, files in os.walk("config/extensions"):
		for file in files:
			if file == "requirements.txt":
				with open(os.path.join(root, file)) as extension_requirements:
					for line in extension_requirements.readlines():
						extension_packages.add(line.strip())
	if extension_packages:
		print("Found extensions, installing additional packages: " + str(extension_packages))
		packages = packages.union(extension_packages)

# Some packages don't run on Windows
unix_packages = {
	"python-daemon==2.3.2"
}

if os.name != "nt":
	packages |= unix_packages

setup(
	name='fourcat',
	version=version,
	description=('4CAT: Capture and Analysis Tool is a comprehensive tool for '
				 'analysing discourse on online social platforms'),
	long_description=readme,
	author="Open Intelligence Lab / Digital Methods Initiative",
	author_email="4cat@oilab.eu",
	url="https://4cat.nl",
	packages=['backend', 'webtool', 'datasources'],
	python_requires='>=3.11',
	install_requires=list(packages),
)
