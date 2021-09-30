FROM debian:buster

RUN apt-get update && apt install -y \
    curl \
    git \
    gawk \
    libpq-dev \
    netcat \
    postgresql-client \
    postgresql-server-dev-all \
    python3-dev \
    python3-pip \
    unzip \
    wget \
    xvfb 

WORKDIR /usr/src/app

# Install google chrome
RUN wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
RUN dpkg -i google-chrome-stable_current_amd64.deb; apt-get -fy install

ENV DISPLAY=:99
ENV CHROME_BIN=/usr/bin/google-chrome

# install chromedriver
RUN wget -O /tmp/chromedriver.zip http://chromedriver.storage.googleapis.com/`curl -sS chromedriver.storage.googleapis.com/LATEST_RELEASE`/chromedriver_linux64.zip
RUN unzip /tmp/chromedriver.zip chromedriver -d /usr/local/bin/

# install dependencies
RUN pip3 install --upgrade pip
COPY ./requirements.txt /usr/src/app/requirements.txt
COPY ./setup.py /usr/src/app/setup.py
COPY ./VERSION /usr/src/app/VERSION
COPY ./README.md /usr/src/app/README.md
RUN mkdir /usr/src/app/backend
RUN mkdir /usr/src/app/webtool
RUN mkdir /usr/src/app/datasources
RUN pip3 install -r requirements.txt

# Frontend requirements
RUN pip3 install gunicorn

# Copy project
COPY . /usr/src/app/
