from setuptools import setup
import os

with open("README.md", 'r') as readmefile:
	readme = readmefile.read()

# Universal libraries
libraries = [
		"requests==2.20.0",
		"psycopg2_binary==2.7.5",
		"pymysql==0.9.2",
		"html2text==2018.1.9",
		"numpy==1.15.2",
		"scipy==1.1.0",
		"stop_words==2018.7.23",
		"setuptools==40.0.0",
		"psutil==5.4.7",
		"Flask==1.1.0",
		"pandas==0.23.4",
		"gensim==3.6.0",
		"matplotlib==3.0.0",
		"mpld3==0.3",
		"APScheduler==3.5.3",
		"Flask_Limiter==1.0.1",
		"Flask_Login==0.4.1",
		"nltk==3.4.1",
		"Pillow==5.3.0",
		"adjustText==0.7.3",
		"psycopg2==2.7.5",
		"scikit_learn==0.20.0",
		"bcrypt==3.1.4",
		"markdown==3.0.1",
		"cssselect==1.0.3",
		"youtube_dl==2019.1.2",
		"google-api-python-client==1.7.7",
		"datedelta==1.3"
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
	packages=['backend', 'webtool'],
	install_requires=libraries
)