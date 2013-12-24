from celery import Celery


__author__ = 'bkeroack'

celery_app = Celery('daft_tasks')
celery_app.config_from_object('celeryconfig')

