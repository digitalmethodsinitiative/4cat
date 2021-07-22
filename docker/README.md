# Docker Setup
See the latest here:
https://github.com/digitalmethodsinitiative/4cat/wiki/Installing-4CAT#install-4cat-via-docker

## Quick guide
1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop), and start it. Note that on Windows, you may need to ensure that WSL (Windows Subsystem for Linux) integration is enabled in Docker. You can find this in the Docker setting in Settings -> Resources-> WSL Integration -> Enable integration with required distros.
3. Clone the 4CAT repository, or download the most recent [release](https://github.com/digitalmethodsinitiative/4cat/releases) and unzip it somewhere.
4. In a terminal, navigate to the folder in which you just installed 4CAT
5. Optionally, if you know what you are doing, you can copy `config.py-example` to `config.py` and edit 4CAT's configuration before building it. The default configuration will be sufficient in most cases.
6. Run the command `docker-compose up`
7. If this is the first time you're starting the Docker container, it will take a while for all components to be built. Keep an eye on the output: the login data for the 4CAT interface will be displayed here.
8. Once this is done, you can access the 4CAT interface via `http://localhost:80`.

Note: if your computer/server is already using some of the same ports that Docker wishes to use, you can modify the `.env` file in the home directory and change the ports that Docker uses. Any modifications to configuration files will require you to rebuild the docker images with `docker-compose up --build`.

## Docker Trouble shooting

1. localhost does not load and '4cat_frontend exited with code 3' found in console
On the first build, the backend must run prior to the frontend starting. Sometimes this does not occur. You can start 4cat_frontend either via the Docker console or the command `docker start 4cat_frontend`

2. localhost returns 'Secure Connection Failed'
By default this 4CAT Docker setup uses http instead of https. Many browsers will attempt https if they cannot first connect to http. Type 'http://localhost' into your browser bar.

3. ERROR: Service 'backend' failed to build : Build failed
If you run into this and see "error from sender: context canceled", there may be an issue with buildkit. This has been seen with Docker Engine v20.10.7. You can disable it like so:

```
# bash
export DOCKER_BUILDKIT=0
export COMPOSE_DOCKER_CLI_BUILD=0

# windows
set DOCKER_BUILDKIT=0
set COMPOSE_DOCKER_CLI_BUILD=0

# then run docker-compose like normal
docker-compose up
```

References:
https://github.com/docker/buildx/issues/426
https://stackoverflow.com/questions/64221861/failed-to-resolve-with-frontend-dockerfile-v0

4. More errors coming soon! (No doubt)
