import os
import configparser
import bcrypt
from pathlib import Path

DOCKER_CONFIG_FILE = 'docker/docker_config.ini'

if os.path.exists(DOCKER_CONFIG_FILE):
    config = configparser.ConfigParser()
    config.read(DOCKER_CONFIG_FILE)

    # Change config to use docker variables
    config['DOCKER']['use_docker_config'] = 'True'

    # Generate salt and secret_key if they do not exist
    if config['GENERATE'].get('anonymisation_salt', 'REPLACE_THIS') == 'REPLACE_THIS':
        config['GENERATE']['anonymisation_salt'] = bcrypt.gensalt().decode('utf-8')
    if config['GENERATE'].get('secret_key', 'REPLACE_THIS') == 'REPLACE_THIS':
        config['GENERATE']['secret_key'] = bcrypt.gensalt().decode('utf-8')

    with open(DOCKER_CONFIG_FILE, 'w') as configfile:
        config.write(configfile)

    # Ensure filepaths exist
    import config
    if Path(config.PATH_ROOT, config.PATH_DATA).is_dir():
        pass
    else:
        os.makedirs(Path(config.PATH_ROOT, config.PATH_DATA))

    if Path(config.PATH_ROOT, config.PATH_IMAGES).is_dir():
        pass
    else:
        os.makedirs(Path(config.PATH_ROOT, config.PATH_IMAGES))

    if Path(config.PATH_ROOT, config.PATH_LOGS).is_dir():
        pass
    else:
        os.makedirs(Path(config.PATH_ROOT, config.PATH_LOGS))

    if Path(config.PATH_ROOT, config.PATH_LOCKFILE).is_dir():
        pass
    else:
        os.makedirs(Path(config.PATH_ROOT, config.PATH_LOCKFILE))
