from celery import Celery
from flask import Flask

app = Flask(__name__)
	
import fourcat.views

app.config.from_object('config')

def make_celery(app):
	celery = Celery(
		app.import_name,
		backend=app.config['CELERY_RESULT_BACKEND'],
		broker=app.config['CELERY_BROKER_URL'])
	celery.conf.update(app.config)
	#celery.config_from_object('celeryconfig')
	TaskBase = celery.Task
	class ContextTask(TaskBase):
		abstract = True
		def __call__(self, *args, **kwargs):
			with app.app_context():
				return TaskBase.__call__(self, *args, **kwargs)
	celery.Task = ContextTask
	return celery

celery = make_celery(app)

@celery.task()
def add_together(a, b):
	return a + b

if __name__ == "__main__":
	print('Starting server...')
	app.run(debug=True)