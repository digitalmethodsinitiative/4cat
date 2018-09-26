import celery

@celery.task()
def print_hello():
	#return 'hallo'
	logger = print_hello.get_logger()
	logger.info("Hello")