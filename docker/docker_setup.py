"""
Creates and/or manages the 4CAT configuration file located at
config/config.ini.

For Docker, it is necessary to keep this file in a shared volume as both the
backend and frontend use it. The config_manager will also read and edit this
file. Some variables are defined via the Docker configurations (such as db_host
or db_port) while others can be set by the user in the `.env` file which is
read by a docker-compose.yml.

This should be run from the command line and is used by docker-entrypoint files.
"""

from urllib.parse import urlsplit
import ipaddress


def update_config_from_environment(CONFIG_FILE, config_parser):
    """
    Use OS environmental variables to update 4CAT database settings
    """
    ################
    # User Defined #
    ################
    # Per the Docker .env file; required for docker-entrypoint.sh and db setup

    # Server information (Public Port can be updated via .env, but server name can also be update via frontend)
    config_parser['SERVER']['public_port'] = os.environ['PUBLIC_PORT']

    # Set API
    config_parser['API']['api_host'] = os.environ['API_HOST']  # set in .env; should be backend container_name in docker-compose.py unless frontend and backend are running together in one container

    # Database configuration
    config_parser['DATABASE']['db_name'] = os.environ['POSTGRES_DB']
    config_parser['DATABASE']['db_host'] = os.environ['POSTGRES_HOST']
    config_parser['DATABASE']['db_port'] = os.environ['POSTGRES_PORT']
    config_parser['DATABASE']['db_user'] = os.environ['POSTGRES_USER']
    config_parser['DATABASE']['db_password'] = os.environ['POSTGRES_PASSWORD']
    config_parser['DATABASE']['db_host_auth'] = os.environ['POSTGRES_HOST_AUTH_METHOD']

    # Memcached settings
    if 'MEMCACHED_HOST' in os.environ and 'MEMCACHED_PORT' in os.environ:
        if "MEMCACHE" not in config_parser:
            config_parser.add_section('MEMCACHE')
        config_parser['MEMCACHE']['memcache_host'] = os.environ['MEMCACHED_HOST'] + f":{os.environ['MEMCACHED_PORT']}"
    else:
        # If not set, remove the section if it exists
        if 'MEMCACHE' in config_parser:
            config_parser.remove_section('MEMCACHE')

    # Save config file
    with open(CONFIG_FILE, 'w') as configfile:
        config_parser.write(configfile)


# Helpers for robust SERVER_NAME handling in Docker


def _extract_host_port(value: str):
    v = (value or "").strip().rstrip("/")
    if "://" not in v:
        v = f"http://{v}"
    parts = urlsplit(v)
    host = parts.hostname or ""
    port = parts.port
    return host, port


def _is_ip_or_localhost(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def _format_host(host: str) -> str:
    # Bracket IPv6 literals when emitting host[:port]
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


if __name__ == "__main__":
    import os
    import configparser
    import bcrypt

    # Configuration file location
    CONFIG_FILE = 'config/config.ini'

    # Check if file does not already exist
    if not os.path.exists(CONFIG_FILE):
        # Create the config file
        print('Creating config/config.ini file')
        config_parser = configparser.ConfigParser()

        # Flag 4CAT as using Docker
        # This tells config_manager.py that we are using Docker
        config_parser.add_section('DOCKER')
        config_parser['DOCKER']['use_docker_config'] = 'True'

        # Database information stored here
        config_parser.add_section('DATABASE')

        # Flask server information
        config_parser.add_section('SERVER')

        # Backend API
        config_parser.add_section('API')
        config_parser['API']['api_port'] = '4444'  # backend internal port set in docker-compose.py; NOT API_PUBLIC_PORT as that is what port Docker exposes to host network

        # File paths
        # Docker volumes are defined in docker-compose.yml; these rely on one shared volume `data` in the 4CAT root directory
        config_parser.add_section('PATHS')
        config_parser['PATHS']['path_images'] = 'data/images'  # shared volume defined in docker-compose.yml
        config_parser['PATHS']['path_data'] = 'data/datasets'  # shared volume defined in docker-compose.yml
        config_parser['PATHS']['path_lockfile'] = 'backend'  # docker-entrypoint.sh looks for pid file here (in event Docker shutdown was not clean)
        config_parser['PATHS']['path_sessions'] = 'data/sessions'  # shared volume defined in docker-compose.yml
        config_parser['PATHS']['path_logs'] = 'data/logs/'  # shared volume defined in docker-compose.yml

        # Generated variables
        config_parser.add_section('GENERATE')
        config_parser['GENERATE']['anonymisation_salt'] = bcrypt.gensalt().decode('utf-8')
        config_parser['GENERATE']['secret_key'] = bcrypt.gensalt().decode('utf-8')

        # Write environment variables to database
        # Must write prior to importing config (where the values are read)
        update_config_from_environment(CONFIG_FILE, config_parser)
        print('Created config/config.ini file')

        # Ensure filepaths exist
        from common.config_manager import ConfigManager
        from common.lib.database import Database

        config = ConfigManager()
        config.with_db(Database(logger=None, appname="docker-setup",
				  dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST, port=config.DB_PORT))

        for path in [config.get('PATH_DATA'),
                     config.get('PATH_IMAGES'),
                     config.get('PATH_LOGS'),
                     config.get('PATH_LOCKFILE'),
                     config.get('PATH_SESSIONS'),
                     config.get('PATH_EXTENSIONS')
                     ]:
            if config.get('PATH_ROOT').joinpath(path).is_dir():
                pass
            else:
                os.makedirs(config.get('PATH_ROOT').joinpath(path))

        # Use .env provided SERVER_NAME on first run with simple, safe rules
        frontend_servername_raw = os.environ['SERVER_NAME']
        # On first run, assume HTTP (port 80). Users can enable HTTPS later.
        default_port = 80
        public_port = int(config_parser['SERVER']['public_port'])

        host, explicit_port = _extract_host_port(frontend_servername_raw)

        if explicit_port is not None:
            servername_value = f"{_format_host(host)}:{explicit_port}"
        else:
            if _is_ip_or_localhost(host):
                if public_port != default_port:
                    servername_value = f"{_format_host(host)}:{public_port}"
                else:
                    servername_value = _format_host(host)
            else:
                servername_value = _format_host(host)

        config.set('flask.server_name', servername_value)
        config.db.commit()

    # Config file already exists; Update .env variables if they changed
    else:
        print('Configuration file config/config.ini already exists')
        print('Checking Docker .env variables and updating if necessary')
        config_parser = configparser.ConfigParser()
        config_parser.read(CONFIG_FILE)

        # Write environment variables to database
        # Must write prior to importing config (which reads these values)
        update_config_from_environment(CONFIG_FILE, config_parser)

        # Check to see if flask.server_name needs to be updated
        from common.config_manager import ConfigManager
        from common.lib.database import Database
        config = ConfigManager()
        config.with_db(Database(logger=None, appname="docker-setup",
				  dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD, host=config.DB_HOST, port=config.DB_PORT))
        
        public_port = int(config_parser['SERVER']['public_port'])
        # Port handling here is independent from HTTPS; default is 80
        default_port = 80

        current = config.get('flask.server_name')
        host, existing_port = _extract_host_port(current)

        # Warn only when localhost/IP lacks a required non-default port
        if existing_port is None and _is_ip_or_localhost(host) and public_port != default_port:
            formatted_host = _format_host(host)
            print(f"Exposed PUBLIC_PORT {public_port} from .env file not included in Server Name; if you are not using a reverse proxy, you may need to update the Server Name variable.")
            print(
                "You can do so by running the following command if you do not have access to the 4CAT frontend Control Panel:\n"
                f"docker exec 4cat_backend python -c \"from common.config_manager import ConfigManager;config=ConfigManager();config.with_db();config.set('flask.server_name', '{formatted_host}:{public_port}');config.db.commit();\""
            )

    print(f"\nStarting app\n"
          f"4CAT is accessible at:\n"
          f"{'https' if config.get('flask.https', False) else 'http'}://{config.get('flask.server_name')}\n")
