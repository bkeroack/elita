#!/bin/bash


if [ -f /home/ubuntu/daft/celeryd.pid ]; then
	PID=$(cat /home/ubuntu/daft/celeryd.pid)
	kill $PID
else
	echo "celeryd not running (celeryd.pid not found)"

fi


