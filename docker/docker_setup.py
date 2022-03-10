import os
import configparser
import bcrypt
from pathlib import Path

DOCKER_CONFIG_FILE = 'docker/shared/docker_config.ini'

if os.path.exists(DOCKER_CONFIG_FILE):
    docker_config = configparser.ConfigParser()
    docker_config.read(DOCKER_CONFIG_FILE)

    # Change config to use docker variables
    # This tells config.py that we are set up for Docker
    docker_config['DOCKER']['use_docker_config'] = 'True'

    # Generate salt and secret_key if they do not exist
    if docker_config['GENERATE'].get('anonymisation_salt', 'REPLACE_THIS') == 'REPLACE_THIS':
        docker_config['GENERATE']['anonymisation_salt'] = bcrypt.gensalt().decode('utf-8')
    if docker_config['GENERATE'].get('secret_key', 'REPLACE_THIS') == 'REPLACE_THIS':
        docker_config['GENERATE']['secret_key'] = bcrypt.gensalt().decode('utf-8')

    # Database configuration
    docker_config['DATABASE']['db_name'] = os.environ['POSTGRES_DB']
    docker_config['DATABASE']['db_user'] = os.environ['POSTGRES_USER']
    docker_config['DATABASE']['db_password'] = os.environ['POSTGRES_PASSWORD']

    # Ensure Flask knows public port
    public_port = os.environ['PUBLIC_PORT']
    docker_config['SERVER']['public_port'] = public_port

        # Save config file
    with open(DOCKER_CONFIG_FILE, 'w') as configfile:
        docker_config.write(configfile)

    import common.config_manager as config
    # Ensure filepaths exist
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

    # Update some settings
    your_server = config.get('SERVER_NAME', 'localhost')
    if public_port == 80:
      pass
    else:
      config.set_value('SERVER_NAME', f"{your_server}:{public_port}")

    whitelist = config.get('HOSTNAME_WHITELIST')# only these may access the web tool; "*" or an empty list matches everything
    if your_server not in whitelist:
        whitelist.append(your_server)
        config.set_value('HOSTNAME_WHITELIST', whitelist)

    api_whitelist = config.get('HOSTNAME_WHITELIST_API')# hostnames matching these are exempt from rate limiting
    if your_server not in api_whitelist:
        api_whitelist.append(your_server)
        config.set_value('HOSTNAME_WHITELIST_API', api_whitelist)
