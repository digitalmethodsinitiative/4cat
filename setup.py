from setuptools import setup
import os

with open("README.md", 'r') as readmefile:
	readme = readmefile.read()

with open("VERSION") as versionfile:
	version = versionfile.readline().strip()

# Universal packages
packages = [
	"google_api_python_client==2.0.2",
	"emoji_country_flag==1.1.0",
	"python_dateutil==2.8.1",
	"selenium_wire==1.0.11",
	"beautifulsoup4==4.9.3",
	"scikit_learn==0.24.1",
	"Flask_Limiter==1.0.1",
	"pyahocorasick==1.4.0",
	"html2text==2018.1.9",
	"cryptography==2.6.1",
	"instaloader==4.5.3",
	"Flask_Login==0.4.1",
	"selenium==3.141.0",
	"dateparser==1.0.0",
	"Werkzeug==0.15.5",
	"ImageHash==4.2.0",
	"requests==2.25.1",
	"Telethon==1.10.6",
	"psycopg2==2.8.6",
	"Markdown==3.0.1",
	"svgwrite==1.3.1",
	"PyTumblr==0.1.0",
	"prawcore==1.5.0",
	"PyMySQL==0.9.2",
	"datedelta==1.3",
	"anytree==2.7.2",
	"pandas==1.2.3",
	"gensim==3.8.3",
	"bcrypt==3.1.4",
	"psutil==5.6.6",
	"numpy>=1.19.2",
	"Pillow>=8.1.2",
	"Flask==1.1.0",
	"spacy==3.0.5",
	"six==1.15.0",
	"lxml==4.6.2",
	"praw==6.5.1",
	"flag==0.1.1",
	"nltk==3.5",
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
	install_requires=packages
)
