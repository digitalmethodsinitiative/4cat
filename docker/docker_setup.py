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

if __name__ == "__main__":
    import os
    import sys
    import configparser
    import bcrypt
    from pathlib import Path

    if len(sys.argv) > 1:
        public = False#sys.argv[1]
    else:
        public = False

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

        config_parser.add_section('DATABASE')
        config_parser['DATABASE']['db_host'] = 'db' # database service name in docker-compose.py
        config_parser['DATABASE']['db_port'] = '5432' # port exposed by postgres image

        config_parser.add_section('API')
        config_parser['API']['api_host'] = '4cat_backend' # backend container_name in docker-compose.py
        config_parser['API']['api_port'] = '4444' # backend port exposed in docker-compose.py

        # File paths
        config_parser.add_section('PATHS')
        config_parser['PATHS']['path_images'] = 'data' # shared volume defined in docker-compose.yml
        config_parser['PATHS']['path_data'] = 'data' # shared volume defined in docker-compose.yml
        config_parser['PATHS']['path_lockfile'] = 'backend' # docker-entrypoint.sh looks for pid file here (in event Docker shutdown was not clean)
        config_parser['PATHS']['path_sessions'] = 'config/sessions'  # shared volume defined in docker-compose.yml
        config_parser['PATHS']['path_logs'] = 'logs/' # shared volume defined in docker-compose.yml

        # Generated variables
        config_parser.add_section('GENERATE')
        config_parser['GENERATE']['anonymisation_salt'] = bcrypt.gensalt().decode('utf-8')
        config_parser['GENERATE']['secret_key'] = bcrypt.gensalt().decode('utf-8')

        ################
        # User Defined #
        ################
        # Per the Docker .env file; required for docker-entrypoint.sh and db setup

        # Database configuration
        config_parser['DATABASE']['db_name'] = os.environ['POSTGRES_DB']
        config_parser['DATABASE']['db_user'] = os.environ['POSTGRES_USER']
        config_parser['DATABASE']['db_password'] = os.environ['POSTGRES_PASSWORD']

        # Ensure Flask knows public port
        config_parser.add_section('SERVER')
        public_port = os.environ['PUBLIC_PORT']
        config_parser['SERVER']['public_port'] = public_port
        # TODO: allow server_name to be updated; still need default for access
        config_parser['SERVER']['server_name'] = os.environ['SERVER_NAME']

        # Save config file
        with open(CONFIG_FILE, 'w') as configfile:
            config_parser.write(configfile)
            print('Created config/config.ini file')

        import config
        # Check if config.py has old docker_config info
        # TODO: remove after database config merge
        if hasattr(config, 'DOCKER_CONFIG_FILE'):
            if not Path(config.DOCKER_CONFIG_FILE).is_file():
                os.makedirs(os.path.dirname(config.DOCKER_CONFIG_FILE))
            with open(config.DOCKER_CONFIG_FILE, 'w') as configfile:
                config_parser.write(configfile)

        # Ensure filepaths exist
        for path in [config.PATH_DATA,
                     config.PATH_IMAGES,
                     config.PATH_LOGS,
                     config.PATH_LOCKFILE,
                     config.PATH_SESSIONS,
                     ]:
            if Path(config.PATH_ROOT, path).is_dir():
                pass
            else:
                os.makedirs(Path(config.PATH_ROOT, path))

    # Config file already exists
    else:
        print('Configuration file config/config.ini already exists')
        print('Updating Docker .env variables if necessary')
        config_parser = configparser.ConfigParser()
        config_parser.read(CONFIG_FILE)

        config_parser['DATABASE']['db_name'] = os.environ['POSTGRES_DB']
        config_parser['DATABASE']['db_user'] = os.environ['POSTGRES_USER']
        config_parser['DATABASE']['db_password'] = os.environ['POSTGRES_PASSWORD']

        public_port = os.environ['PUBLIC_PORT']
        config_parser['SERVER']['public_port'] = str(public_port)
        # TODO server_name should be defined elsewhere, but currently it is in .env file
        config_parser['SERVER']['server_name'] = os.environ['SERVER_NAME']

        # Save config file
        with open(CONFIG_FILE, 'w') as configfile:
            config_parser.write(configfile)

        import config
        # Check if config.py has old docker_config info
        # TODO: remove after database config merge
        if hasattr(config, 'DOCKER_CONFIG_FILE'):
            if not Path(config.DOCKER_CONFIG_FILE).is_file():
                os.makedirs(os.path.dirname(config.DOCKER_CONFIG_FILE))
            with open(config.DOCKER_CONFIG_FILE, 'w') as configfile:
                config_parser.write(configfile)
