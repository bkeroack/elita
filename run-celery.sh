#!/bin/bash

~/.virtualenvs/elita/bin/celery -A elita.celeryinit worker -l DEBUG -c 3 -f /var/log/elita/elita-celery-worker.log
