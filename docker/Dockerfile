FROM postgres:latest

RUN apt-get update && apt install -y \
    # General requirements:
    libpq-dev \
    python3-dev \
    python3-pip \
    python3-venv \
    # Needed specifically for single container version of 4CAT
    sudo \
    procps \
    # Called in docker-entrypoint.sh:
    curl \
    netcat \
    postgresql-client \
    postgresql-server-dev-all \
    # Called by 4CAT:
    git \
    # Needed for video processing only (and only technically on backend)
    ffmpeg

# Set working directory
WORKDIR /4cat

# Make and use virtual environment
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies
RUN pip3 install --upgrade pip
COPY ./requirements.txt /4cat/requirements.txt
COPY ./setup.py /4cat/setup.py
COPY ./VERSION /4cat/VERSION
COPY ./README.md /4cat/README.md
RUN mkdir /4cat/backend
RUN mkdir /4cat/webtool
RUN mkdir /4cat/datasources
RUN pip3 install -r requirements.txt

# Install frontend Docker requirements
RUN pip3 install gunicorn

# Copy project
COPY . /4cat/

# Permissions for Docker container
RUN chmod +x docker/wait-for-backend.sh docker/docker-entrypoint-backend-only.sh docker/docker-entrypoint-single-container.sh

# Expose ports (gunicorn 80, 4CAT api 4444, telegram 443)
EXPOSE 80 4444 443

# Environment variables that can be overwritten (most commonly via in .env file)
ENV PYTHONUNBUFFERED=1 \
 AM_I_IN_A_DOCKER_CONTAINER=Yes \
 # Database setup
 POSTGRES_USER=fourcat \
 POSTGRES_PASSWORD=supers3cr3t \
 POSTGRES_DB=fourcat \
 POSTGRES_HOST=localhost \
 POSTGRES_HOST_AUTH_METHOD=trust \
 # Server information
 SERVER_NAME=localhost \
 PUBLIC_PORT=80 \
 API_HOST=localhost \
 PUBLIC_API_PORT=4444 \
 # Telegram needs its own port
 TELEGRAM_PORT=443 \
 # File path (for Docker volume)
 FOURCAT_DATA=/4cat/data/ \
 # Ensure PGDATA is a subfolder of FOURCAT_DATA to ensure Docker volume saves database data!
 PGDATA=/4cat/data/postgres/

# Default entrypoint creates one container running 4cat backend, frontend, and a postgres database
ENTRYPOINT ["docker/docker-entrypoint-single-container.sh"]
