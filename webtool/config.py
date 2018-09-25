FLASK_APP = 'fourcat'
FLASK_DEBUG = True
DEBUG = True
CELERY_RESULT_BACKEND='amqp://localhost',
CELERY_BROKER_URL='amqp://guest@localhost'
SERVER_NAME='localhost:5000'