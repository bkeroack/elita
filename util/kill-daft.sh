#!/bin/bash
#doesn't actually work since reload is a startup option, not action
#only way to reload is to stop and start
export WORKON_HOME=/home/ubuntu/Envs
source /usr/local/bin/virtualenvwrapper.sh
workon daft
/home/ubuntu/Envs/daft/bin/pserve --stop-daemon --pid-file=/var/lib/pyramid/pyramid.pid /home/ubuntu/daft/production.ini
#pkill /home/ubuntu/Envs/daft/bin/python #just to be sure
#rm /home/ubuntu/daft/Data.fs.lock

