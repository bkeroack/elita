BROKER_URL = 'amqp://localhost'
CELERY_RESULT_BACKEND = 'amqp://'

CELERY_TASK_SERIALIZER = 'pickle'
#CELERY_RESULT_SERIALIZER = 'json'
CELERY_ACCEPT_CONTENT = ['pickle', 'json']
