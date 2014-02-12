#!/bin/bash

export WORKON_HOME=/home/ubuntu/Envs
source /usr/local/bin/virtualenvwrapper.sh
workon daft
cd /home/ubuntu/daft

sudo service rabbitmq-server start
sudo /home/ubuntu/Envs/daft/bin/celery -A daft.celeryinit worker -B -f /var/log/daft/celery-worker.log -l DEBUG -c 10 -D --uid=1000

