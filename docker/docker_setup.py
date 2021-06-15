import os
import configparser
import bcrypt
from pathlib import Path
import sys

DOCKER_CONFIG_FILE = 'docker/shared/docker_config.ini'

if os.path.exists(DOCKER_CONFIG_FILE):
    docker_config = configparser.ConfigParser()
    docker_config.read(DOCKER_CONFIG_FILE)

    # Change config to use docker variables
    docker_config['DOCKER']['use_docker_config'] = 'True'

    # Generate salt and secret_key if they do not exist
    if docker_config['GENERATE'].get('anonymisation_salt', 'REPLACE_THIS') == 'REPLACE_THIS':
        docker_config['GENERATE']['anonymisation_salt'] = bcrypt.gensalt().decode('utf-8')
    if docker_config['GENERATE'].get('secret_key', 'REPLACE_THIS') == 'REPLACE_THIS':
        docker_config['GENERATE']['secret_key'] = bcrypt.gensalt().decode('utf-8')

    # Database configuration
    docker_config['DATABASE']['db_name'] = sys.argv[1]
    docker_config['DATABASE']['db_user'] = sys.argv[2]
    docker_config['DATABASE']['db_password'] = sys.argv[3]
    docker_config['DATABASE']['db_port'] = sys.argv[4]

    # Save config file
    with open(DOCKER_CONFIG_FILE, 'w') as configfile:
        docker_config.write(configfile)

    # Ensure filepaths exist
    import config
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
