#!/bin/bash

~/.virtualenvs/daft/bin/celery -A elita.celeryinit worker -l DEBUG -c 3
