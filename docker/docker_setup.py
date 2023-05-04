"""
Creates and/or manages the 4CAT configuration file located at
data/config/config.ini.

For Docker, it is necessary to keep this file in a shared volume as both the
backend and frontend use it. The config_manager will also read and edit this
file. Some variables are defined via the Docker configurations (such as db_host
or db_port) while others can be set by the user in the `.env` file which is
read by a docker-compose.yml.

This should be run from the command line and is used by docker-entrypoint files.
"""
import configparser
import os
import sys
import bcrypt
from pathlib import Path


def update_config_from_environment(CONFIG_FILE, config_parser):
    """
    Use OS environmental variables to update 4CAT database settings
    """
    ################
    # User Defined #
    ################
    # Per the Docker .env file; required for docker-entrypoint-backend-only.sh and db setup

    # Server information (Public Port can be updated via .env, but server name can also be updated via frontend)
    config_parser['SERVER']['public_port'] = os.environ['PUBLIC_PORT']

    # Set API
    config_parser['API']['api_host'] = os.environ['API_HOST']  # set in .env; should be backend container_name in docker-compose.py unless frontend and backend are running together in one container

    # Database configuration
    config_parser['DATABASE']['db_name'] = os.environ['POSTGRES_DB']
    config_parser['DATABASE']['db_host'] = os.environ['POSTGRES_HOST']
    config_parser['DATABASE']['db_user'] = os.environ['POSTGRES_USER']
    config_parser['DATABASE']['db_password'] = os.environ['POSTGRES_PASSWORD']
    config_parser['DATABASE']['db_host_auth'] = os.environ['POSTGRES_HOST_AUTH_METHOD']

    # File paths
    if "PATHS" not in config_parser:
        config_parser.add_section("PATHS")
    config_parser['PATHS']['path_lockfile'] = 'backend'  # docker-entrypoint files look for pid file here (in event Docker shutdown was not clean)

    if 'FOURCAT_DATA' in os.environ:
        # Single volume (or no volume)
        print(f"All persistent data to be saved in {os.environ['FOURCAT_DATA']}")
        config_parser['PATHS']['path_data'] = os.environ['FOURCAT_DATA'] + '/datasets/'
        config_parser['PATHS']['path_images'] = os.environ['FOURCAT_DATA'] + '/images/'
        config_parser['PATHS']['path_logs'] = os.environ['FOURCAT_DATA'] + '/logs/'
        config_parser['PATHS']['path_sessions'] = os.environ['FOURCAT_DATA'] + '/config/sessions/'

    # Pre 1.34 shared volumes defined in .env and docker-compose.yml
    # These are preferred over FOURCAT_DATA as they are more specific and may not follow the single volume logic
    if 'DATASETS_PATH' in os.environ:
        # Multi-volumes
        print(f"Pre 4CAT v1.34 data volume detected; mapped to {os.environ['DATASETS_PATH']}")
        config_parser['PATHS']['path_data'] = os.environ['DATASETS_PATH']
        config_parser['PATHS']['path_images'] = os.environ['DATASETS_PATH']
    elif 'FOURCAT_DATA' not in os.environ:
        # Pre 1.34 setup
        print("Sysadmin has not updated .env or docker-compose.yml; using default data path")
        config_parser['PATHS']['path_data'] = 'data/'
        config_parser['PATHS']['path_images'] = 'data/'

    if 'LOGS_PATH' in os.environ:
        # Multi-volumes
        print(f"Pre 4CAT v1.34 logs volume detected; mapped to {os.environ['LOGS_PATH']}")
        config_parser['PATHS']['path_logs'] = os.environ['LOGS_PATH']
    elif 'FOURCAT_DATA' not in os.environ:
        # Pre 1.34 setup
        print("Sysadmin has not updated .env or docker-compose.yml; using default log path")
        config_parser['PATHS']['path_logs'] = 'logs/'

    if 'CONFIG_PATH' in os.environ:
        # Multi-volumes
        print(f"Pre 4CAT v1.34 config volume detected; mapped to {os.environ['CONFIG_PATH']}")
        config_parser['PATHS']['path_sessions'] = os.environ['CONFIG_PATH'] + 'sessions/'
    elif 'FOURCAT_DATA' not in os.environ:
        # Pre 1.34 setup
        print("Sysadmin has not updated .env or docker-compose.yml; using default config path")
        config_parser['PATHS']['path_sessions'] = 'config/sessions/'

    # Save config file
    with open(CONFIG_FILE, 'w') as configfile:
        config_parser.write(configfile)


def create_config_ini_file(CONFIG_FILE):
    print(f"Creating {CONFIG_FILE} file")
    config_parser = configparser.ConfigParser()

    # Flag 4CAT as using Docker
    # This tells config_manager.py that we are using Docker
    config_parser.add_section('DOCKER')
    config_parser['DOCKER']['use_docker_config'] = 'True'

    config_parser.add_section('DATABASE')
    config_parser['DATABASE']['db_port'] = '5432'  # port exposed by postgres image

    # Flask server information
    config_parser.add_section('SERVER')

    # Backend API
    config_parser.add_section('API')
    config_parser['API']['api_port'] = '4444'  # backend internal port set in docker-compose.py; NOT API_PUBLIC_PORT as that is what port Docker exposes to host network

    # Generated variables
    config_parser.add_section('GENERATE')
    config_parser['GENERATE']['anonymisation_salt'] = bcrypt.gensalt().decode('utf-8')
    config_parser['GENERATE']['secret_key'] = bcrypt.gensalt().decode('utf-8')

    # Write environment variables to database
    # Must write prior to import common.config_manager as config
    update_config_from_environment(CONFIG_FILE, config_parser)
    print(f"Created {CONFIG_FILE} file")

    # Ensure filepaths exist
    if "common.config_manager" in sys.modules:
        import importlib
        importlib.reload(sys.modules['common.config_manager'])
    import common.config_manager as config

    for path in [config.get('PATH_DATA'),
                 config.get('PATH_IMAGES'),
                 config.get('PATH_LOGS'),
                 config.get('PATH_LOCKFILE'),
                 config.get('PATH_SESSIONS'),
                 ]:
        if Path(config.get('PATH_ROOT'), path).is_dir():
            pass
        else:
            os.makedirs(Path(config.get('PATH_ROOT'), path))

    # Use .env provided SERVER_NAME on first run
    frontend_servername = os.environ['SERVER_NAME']
    # Default to Docker defined port
    docker_port = int(config_parser['SERVER']['public_port'])
    config.set_or_create_setting('docker.frontend_port', docker_port, raw=False)
    # Default public_port to False; can be updated if using port forwarding
    config.set_or_create_setting('docker.port_forwarding', False, raw=False)
    if docker_port == 80:
        config.set_or_create_setting('flask.server_name', frontend_servername, raw=False)
    else:
        config.set_or_create_setting('flask.server_name', f"{frontend_servername}:{docker_port}", raw=False)

    return config


if __name__ == "__main__":
    # Configuration file location
    if 'FOURCAT_DATA' in os.environ:
        CONFIG_FILE = str(Path(os.environ['FOURCAT_DATA']).joinpath("config/config.ini"))
    else:
        CONFIG_FILE = 'data/config/config.ini'

    # Check if file does not already exist
    if not os.path.exists(CONFIG_FILE):
        # Create the config file
        config = create_config_ini_file(CONFIG_FILE)

    # Config file already exists; Update .env variables if they changed
    else:
        print('Configuration file data/config/config.ini already exists')
        print('Checking Docker .env variables and updating if necessary')
        config_parser = configparser.ConfigParser()
        config_parser.read(CONFIG_FILE)

        # Write environment variables to database
        # Must write prior to import common.config_manager as config
        update_config_from_environment(CONFIG_FILE, config_parser)

        # Check to see if flask.server_name needs to be updated
        import common.config_manager as config
        new_docker_port = int(config_parser['SERVER']['public_port'])
        old_docker_port = config.get("docker.frontend_port")
        port_forwarded = int(config.get('docker.port_forwarding', False))
        frontend_servername = config.get('flask.server_name').split(":")[0]

        if old_docker_port is None:
            # Updated from previous 4CAT version
            config.set_or_create_setting('docker.frontend_port', new_docker_port, raw=False)
            if not port_forwarded:
                # No frontend_port set, update server_name based on Docker
                config.set_or_create_setting('flask.server_name',
                                             f"{frontend_servername}{(':' + str(new_docker_port)) if new_docker_port != 80 else ''}",
                                             raw=False)

        elif new_docker_port != int(config.get("docker.frontend_port")):
            print(f"Docker frontend port changed in .env file; updating...")
            # Update docker port
            config.set_or_create_setting('docker.frontend_port', new_docker_port, raw=False)
            if not port_forwarded:
                # No frontend_port set, update server_name based on Docker change
                config.set_or_create_setting('flask.server_name', f"{frontend_servername}{(':'+str(new_docker_port)) if new_docker_port != 80 else ''}", raw=False)
                print(f"docker.port_forwarding False; updated flask.server_name based on Docker port: {frontend_servername}:{new_docker_port}")
            else:
                print(f"docker.port_forwarding True, ensure port forwarding to Docker container port {new_docker_port}")

    print(f"\nStarting app\n"
          f"4CAT is accessible at:\n"
          f"{'https' if config.get('flask.https', False) else 'http'}://{config.get('flask.server_name')}\n")
