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

    # Ensure Flask knows public host and port
    docker_config['SERVER']['server_name'] = os.environ['SERVER_NAME']
    docker_config['SERVER']['public_port'] = os.environ['PUBLIC_PORT']

    # Install specific packages
    if docker_config['DOCKER'].getboolean('new_installation'):
        # NLTK resources
        import nltk
        nltk.download("wordnet")
        nltk.download("punkt")

        # Spacy lexicon
        import spacy
        spacy.cli.download('en_core_web_sm')

        # Update config to skip this on future runs
        docker_config['DOCKER']['new_installation'] = 'False'

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
