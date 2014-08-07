#!/bin/bash

apt-get install -y mongodb rabbitmq-server python-pip python-dev libssl-dev swig git nginx curl jq
cd /home/vagrant/elita
python ./setup.py develop
cd /home/vagrant/elita_scorebig
python ./setup.py develop
cd /home/vagrant/elita
# sometimes the elita_scorebig install will clobber the elita module with a really old version. no idea why.
python ./setup.py develop
elita_install

[ -d "/etc/nginx/ssl" ] || mkdir /etc/nginx/ssl
cp /srv/nginx/cert.* /etc/nginx/ssl/
ln -s /etc/nginx/sites-available/elita /etc/nginx/sites-enabled/
service nginx restart

cp /srv/keys/minion0.pub /etc/salt/pki/master/minions/server0
cp /srv/keys/minion1.pub /etc/salt/pki/master/minions/server1
cp /srv/keys/minion2.pub /etc/salt/pki/master/minions/server2
cp /srv/keys/minion3.pub /etc/salt/pki/master/minions/server3

#have to restart salt to get it to accept keys
service salt-master stop
killall salt-master
sleep 5
service salt-master start
