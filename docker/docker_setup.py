import os
import sys
import configparser
import bcrypt
from pathlib import Path

DOCKER_CONFIG_FILE = 'docker/shared/docker_config.ini'

# If Docker config already exists, exit
if os.path.exists(DOCKER_CONFIG_FILE):
    print('Configuration file docker_config.ini already exists')
    print('Updating Docker .env variables if necessary')
    docker_config = configparser.ConfigParser()
    docker_config.read(DOCKER_CONFIG_FILE)

    docker_config['DATABASE']['db_name'] = os.environ['POSTGRES_DB']
    docker_config['DATABASE']['db_user'] = os.environ['POSTGRES_USER']
    docker_config['DATABASE']['db_password'] = os.environ['POSTGRES_PASSWORD']

    public_port = os.environ['PUBLIC_PORT']
    docker_config['SERVER']['public_port'] = str(public_port)

    # Save config file
    with open(DOCKER_CONFIG_FILE, 'w') as configfile:
        docker_config.write(configfile)

    import common.config_manager as config
    your_server = config.get('SERVER_NAME', 'localhost')
    if int(public_port) == 80:
      config.set_value('SERVER_NAME', your_server)
    else:
      config.set_value('SERVER_NAME', f"{your_server}:{public_port}")

    # Exit
    exit(0)

###################
# Docker settings #
###################

# Create Docker Config file
docker_config = configparser.ConfigParser()

# Flag 4CAT as using Docker
# This tells config_manager.py that we are using Docker
docker_config.add_section('DOCKER')
docker_config['DOCKER']['use_docker_config'] = 'True'

docker_config.add_section('DATABASE')
docker_config['DATABASE']['db_host'] = 'db' # database service name in docker-compose.py
docker_config['DATABASE']['db_port'] = '5432' # port exposed by postgres image

docker_config.add_section('API')
docker_config['API']['api_host'] = '4cat_backend' # backend container_name in docker-compose.py
docker_config['API']['api_port'] = '4444' # backend port exposed in docker-compose.py

# These could perhaps be defined elsewhere
docker_config.add_section('PATHS')
docker_config['PATHS']['path_images'] = 'data'
docker_config['PATHS']['path_data'] = 'data'
docker_config['PATHS']['path_lockfile'] = 'backend'
docker_config['PATHS']['path_sessions'] = 'docker/shared/sessions' # this may need to be in a volume (docker/shared is a volume)
docker_config['PATHS']['path_logs'] = 'logs/'

# Generated variables
docker_config.add_section('GENERATE')
docker_config['GENERATE']['anonymisation_salt'] = bcrypt.gensalt().decode('utf-8')
docker_config['GENERATE']['secret_key'] = bcrypt.gensalt().decode('utf-8')

################
# User Defined #
################
# Per the Docker .env file

# Database configuration
docker_config['DATABASE']['db_name'] = os.environ['POSTGRES_DB']
docker_config['DATABASE']['db_user'] = os.environ['POSTGRES_USER']
docker_config['DATABASE']['db_password'] = os.environ['POSTGRES_PASSWORD']

# Ensure Flask knows public port
docker_config.add_section('SERVER')
public_port = os.environ['PUBLIC_PORT']
docker_config['SERVER']['public_port'] = public_port

# Save config file
with open(DOCKER_CONFIG_FILE, 'w') as configfile:
    docker_config.write(configfile)
    print('Created docker_config.ini file')

#############################
# Update addtional settings #
#############################

# Import confit_manager which will now read these variables
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
if int(public_port) == 80:
    config.set_value('SERVER_NAME', your_server)
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
