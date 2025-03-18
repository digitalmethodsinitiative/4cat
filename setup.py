from setuptools import setup
import os

with open("README.md", 'r') as readmefile:
	readme = readmefile.read()

with open("VERSION") as versionfile:
	version = versionfile.readline().strip()

# Universal packages
packages = set([
	"anytree~=2.8.0",
	"atproto==0.0.57",
	"bcrypt~=3.2.0",
	"beautifulsoup4",#~=4.11.0",
	"clarifai-grpc~=9.0",
	"cryptography>=39.0.1",
	"cssselect~=1.1.0",
	"datedelta~=1.4.0",
	"dateparser~=1.1.0",
	"emoji>=2.12.1",
	"flag",
	"Flask~=2.2",
	"Flask_Limiter==1.0.1",
	"Flask_Login~=0.6",
	"gensim>=4.3.3, <4.4.0",
	"google_api_python_client==2.0.2",
	"html2text==2020.*",
	"ImageHash>4.2.0",
	"jieba~=0.42",
	"json_stream",
	"lxml~=4.9.0",
	"markdown==3.0.1",
	"markdown2==2.4.2",
	"nltk~=3.9.1",
	"networkx~=2.8.0",
	"numpy>=1.19.2",
	"openai==1.59.3",
	"packaging",
	"pandas==1.5.3",
	"Pillow>=10.3",
	"praw~=7.0",
	"prawcore~=2.0",
	"psutil~=5.0",
	"psycopg2~=2.9.0",
	"pyahocorasick~=1.4.0",
	"PyMySQL~=1.0",
	"PyTumblr==0.1.0",
	"razdel~=0.5",
	"requests~=2.27",
	"requests_futures",
	"scenedetect[opencv]",
	"scikit-learn",
	"scipy==1.10.1",
	"shapely",
	"svgwrite~=1.4.0",
	"tailer",
	"Telethon~=1.36.0",
	"ural~=1.3",
	"unidecode~=1.3",
	"Werkzeug~=2.2",
	"wordcloud~=1.8",
	# The https://github.com/akamhy/videohash is not being maintained anymore; these are two patches
	"imagedominantcolor @ git+https://github.com/dale-wahl/imagedominantcolor.git@pillow10",
	"videohash @ git+https://github.com/dale-wahl/videohash@main",
	"vk_api",
	"yt-dlp"
])

# Check for extension packages
if os.path.isdir("extensions"):
	extension_packages = set()
	for root, dirs, files in os.walk("extensions"):
		for file in files:
			if file == "requirements.txt":
				with open(os.path.join(root, file)) as extension_requirements:
					for line in extension_requirements.readlines():
						extension_packages.add(line.strip())
	if extension_packages:
		print("Found extensions, installing additional packages: " + str(extension_packages))
		packages = packages.union(extension_packages)

# Some packages don't run on Windows
unix_packages = set([
	"python-daemon==2.3.2"
])

if os.name != "nt":
	packages = packages.union(unix_packages)

setup(
	name='fourcat',
	version=version,
	description=('4CAT: Capture and Analysis Tool is a comprehensive tool for '
				 'analysing discourse on online social platforms'),
	long_description=readme,
	author="Open Intelligence Lab",
	author_email="4cat@oilab.eu",
	url="https://oilab.eu",
	packages=['backend', 'webtool', 'datasources'],
	python_requires='>=3.7',
	install_requires=list(packages),
)
