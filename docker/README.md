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

---

## Running a local Ollama instance alongside 4CAT

4CAT can use a local [Ollama](https://ollama.com) server for LLM-powered processors.
A Docker Compose override file (`docker-compose_ollama.yml`) is included to add
Ollama as a sidecar service so you do not need to run it separately on the host.

### Quick start

```bash
docker compose -f docker-compose.yml -f docker-compose_ollama.yml up -d
```

This starts the standard 4CAT stack plus an `ollama` container that is only
accessible within the Docker network (and optionally on `localhost:11434` on
the host via the exposed port).

### Configuring 4CAT to use Ollama

1. Log in as admin and open **Control Panel → Settings**.
2. Set the following LLM fields:

   | Setting | Value |
   |---|---|
   | LLM Provider Type | `ollama` |
   | LLM Server URL | `http://ollama:11434` |
   | LLM Access | enabled |

3. Save settings.
4. Open **Control Panel → LLM Server** (visible once *LLM Access* is enabled).
5. Use the **Refresh** button to load available models, then **Pull** a model
   (e.g. `llama3.2:3b`) to download it from the Ollama library.
6. Enable the models you want to make available to users.

### GPU support (NVIDIA)

Uncomment the `deploy.resources` block in `docker-compose_ollama.yml` and
ensure the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
is installed on your host. Then restart the stack with the override:

```bash
docker compose -f docker-compose.yml -f docker-compose_ollama.yml up -d
```

### Persisting models

Models downloaded by Ollama are stored in the `4cat_ollama_data` Docker volume.
They survive container restarts and re-creations unless you explicitly remove
the volume (`docker volume rm 4cat_ollama_data`).

### Using an external Ollama server

If you already run Ollama on the host or elsewhere, skip the override file and
point 4CAT directly at that server:

- **On the same host**: use `http://host.docker.internal:11434` as the LLM Server URL.
- **Remote server**: use the server's reachable URL and configure any required
  API key in the *LLM Server API Key* and *LLM Server Authentication Type* settings.
