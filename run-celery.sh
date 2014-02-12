#!/bin/bash

~/.virtualenvs/daft/bin/celery -A daft.celeryinit worker -l DEBUG -c 2 -B
