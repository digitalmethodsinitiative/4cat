FROM debian:buster

RUN apt update && apt install -y python3-pip libpq-dev python3-dev postgresql-server-dev-all

WORKDIR /usr/src/app

# install dependencies
RUN pip3 install --upgrade pip
COPY ./requirements.txt /usr/src/app/requirements.txt
COPY ./setup.py /usr/src/app/setup.py
COPY ./README.md /usr/src/app/README.md
RUN mkdir /usr/src/app/backend
RUN mkdir /usr/src/app/webtool
RUN mkdir /usr/src/app/datasources
RUN pip3 install -r requirements.txt

RUN pip3 install gunicorn
RUN apt install -y postgresql-client

RUN export PGPASSWORD=test
# copy project
COPY . /usr/src/app/

EXPOSE 5000

ENTRYPOINT ["docker/docker-entrypoint.sh"]