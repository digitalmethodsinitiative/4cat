from setuptools import setup
import os

with open("README.md", 'r') as readmefile:
	readme = readmefile.read()

# Universal libraries
libraries = [
	"google-api-python-client==1.7.7",
	"emoji-country-flag==1.1.0",
	"stop_words==2018.7.23",
	"selenium-wire==1.0.11",
	"scikit_learn==0.20.1",
	"Flask_Limiter==1.0.1",
	"youtube_dl==2019.1.2",
	"pyahocorasick==1.4.0",
	"html2text==2018.1.9",
	"cryptography==2.6.1",
	"instaloader==4.4.4",
	"setuptools==40.8.0",
	"APScheduler==3.5.3",
	"Flask_Login==0.4.1",
	"matplotlib==3.1.1",
	"adjustText==0.7.3",
	"selenium==3.141.0",
	"werkzeug==0.15.5",
	"cssselect==1.0.3",
	"requests==2.20.0",
	"telethon==1.10.6",
	"psycopg2==2.8.4",
	"markdown==3.0.1",
	"jsonpickle==1.2",
	"svgwrite==1.3.1",
	"pytumblr==0.1.0",
	"cython==0.29.14",
	"pymysql==0.9.2",
	"docutils==0.16",
	"pandas==1.0.4",
	"datedelta==1.3",
	"anytree==2.7.2",
	"gensim==3.8.1",
	"psutil==5.6.6",
	"numpy==1.15.2",
	"Pillow==6.2.2",
	"bcrypt==3.1.4",
	"scipy==1.1.0",
	"Flask==1.1.0",
	"spacy==2.2.4",
	"praw==6.5.1",
	"nltk==3.4.5",
	"mpld3==0.3",
	"ijson==2.4",
]

# Some libraries don't run on Windows
unix_libraries = [
	"python-daemon==2.2.0"
]

if os.name != "nt":
	libraries = libraries + unix_libraries

setup(
	name='fourcat',
	version=1,
	description=('4CAT: Capture and Analysis Tool is a comprehensive tool for '
				 'analysing discourse on web forums and imageboards'),
	long_description=readme,
	author="Open Intelligence Lab",
	author_email="4cat@oilab.eu",
	url="https://4cat.oilab.nl",
	packages=['backend', 'webtool', 'datasources'],
	install_requires=libraries
)
