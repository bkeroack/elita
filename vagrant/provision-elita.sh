#!/bin/bash

apt-get install -y mongodb rabbitmq-server python-pip python-dev libssl-dev swig git nginx curl jq httpie htop
cd /home/vagrant/elita
python ./setup.py develop
#cd /home/vagrant/elita_scorebig
#python ./setup.py develop
cd /home/vagrant/elita
#python ./setup.py develop
elita_install

[ -d "/etc/nginx/ssl" ] || mkdir /etc/nginx/ssl
cp /srv/nginx/cert.* /etc/nginx/ssl/
ln -s /etc/nginx/sites-available/elita /etc/nginx/sites-enabled/
service nginx restart

cp /srv/keys/minion0.pub /etc/salt/pki/master/minions/server0
cp /srv/keys/minion1.pub /etc/salt/pki/master/minions/server1
cp /srv/keys/minion2.pub /etc/salt/pki/master/minions/server2
cp /srv/keys/minion3.pub /etc/salt/pki/master/minions/server3
cp /srv/keys/web01.pub /etc/salt/pki/master/minions/web01
cp /srv/keys/web02.pub /etc/salt/pki/master/minions/web02
cp /srv/keys/bus01.pub /etc/salt/pki/master/minions/bus01
cp /srv/keys/bus02.pub /etc/salt/pki/master/minions/bus02

#have to restart salt to get it to accept keys
service salt-master stop
killall salt-master
sleep 5
service salt-master start
