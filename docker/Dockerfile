FROM python:3.11-slim

RUN apt-get update && apt install -y \
    # General requirements:
    libpq-dev \
    python3-dev \
    python3-pip \
    # Called in docker-entrypoint.sh:
    curl \
    netcat-traditional \
    postgresql-client \
    postgresql-server-dev-all \
    # Called by 4CAT:
    git \
    # Needed for video processing only (and only technically on backend)
    ffmpeg \
    # Clean up after apt-get:
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /usr/src/app

# Ensure that Python outputs everything that's printed inside to containers
ENV PYTHONUNBUFFERED=1

# Set up environment for Python setup.py
COPY ./requirements.txt /usr/src/app/requirements.txt
COPY ./setup.py /usr/src/app/setup.py
COPY ./VERSION /usr/src/app/VERSION
COPY ./README.md /usr/src/app/README.md
RUN mkdir /usr/src/app/backend
RUN mkdir /usr/src/app/webtool
RUN mkdir /usr/src/app/datasources
# Install python dependencies
RUN pip3 install --upgrade pip && pip3 install -r requirements.txt

# Install frontend Docker requirements
RUN pip3 install gunicorn

# Copy project
COPY . /usr/src/app/

# Permission
RUN chmod +x docker/wait-for-backend.sh docker/docker-entrypoint.sh
