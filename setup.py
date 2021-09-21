from setuptools import setup
import os

with open("README.md", 'r') as readmefile:
	readme = readmefile.read()

with open("VERSION") as versionfile:
	version = versionfile.readline().strip()

# Universal packages
packages = [
	"anytree==2.7.2",
	"bcrypt==3.1.4",
	"beautifulsoup4==4.9.3",
	"cryptography==3.3.2",
	"cssselect>=1.1.0",
	"datedelta==1.3",
	"dateparser==1.0.0",
	"emoji_country_flag==1.1.0",
	"Flask==1.1.0",
	"Flask_Limiter==1.0.1",
	"Flask_Login==0.4.1",
	"gensim==3.8.3",
	"google_api_python_client==2.0.2",
	"html2text==2018.1.9",
	"ImageHash==4.2.0",
	"instaloader==4.5.3",
	"lxml==4.6.3",
	"Markdown==3.0.1",
	"nltk==3.5",
	"networkx>=2.5.1",
	"numpy>=1.19.2",
	"pandas==1.2.3",
	"Pillow>=8.1.2",
	"praw==7.3.0",
	"prawcore==2.2.0",
	"psutil==5.6.7",
	"psycopg2==2.8.6",
	"pyahocorasick==1.4.0",
	"PyMySQL==0.9.2",
	"python_dateutil==2.8.1",
	"PyTumblr==0.1.0",
	"requests==2.25.1",
	"scikit_learn==0.24.1",
	"selenium_wire==1.0.11",
	"selenium==3.141.0",
	"six==1.15.0",
	"spacy==3.0.5",
	"svgwrite==1.3.1",
	"Telethon==1.10.6",
	"Werkzeug==0.15.5",
	"en_core_web_sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.0.0/en_core_web_sm-3.0.0.tar.gz#egg=en_core_web_sm"
]

# Some packages don't run on Windows
unix_packages = [
	"python-daemon==2.3.0"
]

if os.name != "nt":
	packages = packages + unix_packages

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
	install_requires=packages,
)
