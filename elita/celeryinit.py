from celery import Celery


__author__ = 'bkeroack'

celery = Celery('daft_tasks')
celery.config_from_object('elita.celeryconfig')

