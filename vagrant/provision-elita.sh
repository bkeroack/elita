#!/bin/bash

apt-get install -y mongodb rabbitmq-server python-pip python-dev libssl-dev swig git nginx
cd /home/ubuntu/elita
python ./setup.py install
elita_install

[ -d "/etc/nginx/ssl" ] || mkdir /etc/nginx/ssl
cp /srv/salt/nginx/cert.* /etc/nginx/ssl/
ln -s /etc/nginx/sites-available/elita /etc/nginx/sites-enabled/
service nginx restart

cp /srv/keys/minion0.pub /etc/salt/pki/master/minions/server0
