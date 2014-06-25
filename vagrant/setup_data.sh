#!/bin/bash

SERVER="http://localhost:2718"
AUTH_FILE="/home/vagrant/auth.txt"
PRIVATE_KEY="/home/vagrant/setup-data/private.key"
PUBLIC_KEY="/home/vagrant/setup-data/public.key"
BITBUCKET_USERNAME="/home/vagrant/setup-data/bb_username.txt"
BITBUCKET_PASSWORD="/home/vagrant/setup-data/bb_password.txt"

echo "Getting auth token"
curl -s -XGET "${SERVER}/global/users/admin?password=elita" |jq -r '.message.auth_token[0]' > "${AUTH_FILE}"

echo "Creating Bitbucket credentials"
curl -XPOST -H "Auth-Token: $(cat ${AUTH_FILE})" "${SERVER}/global/keypairs?name=kp0&app_name=testapp&key_type=git&from=files&pretty=true" -F "private_key=@${PRIVATE_KEY}" -F "public_key=@${PUBLIC_KEY}"

USERNAME=$(cat ${BITBUCKET_USERNAME})
PASSWORD=$(cat ${BITBUCKET_PASSWORD})
DATA_STRING='{ "type": "bitbucket", "auth": { "username": '"\"${USERNAME}\""', "password": '"\"${PASSWORD}\""' } }'
curl -XPUT -H "Content-Type: application/json" -H "Auth-Token: $(cat ${AUTH_FILE})" "${SERVER}/global/gitproviders?name=gp0&pretty=true" -d "${DATA_STRING}"

echo "Creating servers"
curl -XPUT -H "Auth-Token: $(cat ${AUTH_FILE})" "${SERVER}/server?name=server0&existing=true&environment=test&pretty=true"

curl -XPUT -H "Auth-Token: $(cat ${AUTH_FILE})" "${SERVER}/server?name=server1&existing=true&environment=test&pretty=true"

curl -XPUT -H "Auth-Token: $(cat ${AUTH_FILE})" "${SERVER}/server?name=server2&existing=true&environment=test&pretty=true"

curl -XPUT -H "Auth-Token: $(cat ${AUTH_FILE})" "${SERVER}/server?name=server3&existing=true&environment=test&pretty=true"

echo "Creating application endpoints"
curl -XPUT -H "Auth-Token: $(cat ${AUTH_FILE})" "${SERVER}/app?app_name=testapp&pretty=true"

curl -XPUT -H "Auth-Token: $(cat ${AUTH_FILE})" "${SERVER}/app/testapp/gitrepos?name=gr0&existing=false&gitprovider=gp0&keypair=kp0&pretty=true"

curl -XPUT -H "Content-Type: application/json" -H "Auth-Token: $(cat ${AUTH_FILE})" "${SERVER}/app/testapp/gitdeploys?name=gd0&pretty=true" -d '{ "package": "master", "location": { "path": "/opt/testapp", "gitrepo": "gr0", "default_branch": "master" } }'

#only run this once all Vagrant boxes are up
curl -XPOST -H "Content-Type: application/json" -H "Auth-Token: $(cat ${AUTH_FILE})" "${SERVER}/app/testapp/gitdeploys/gd0?initialize=true&pretty=true" -d '{ "servers": [ "server0", "server1", "server2", "server3" ] }'



