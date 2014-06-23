#!/bin/bash

SERVER="http://localhost:2718"
AUTH_FILE="/home/elita/auth.txt"
PRIVATE_KEY="/home/vagrant/setup-data/private.key"
PUBLIC_KEY="/home/vagrant/setup-data/public.key"
BITBUCKET_USERNAME="/home/vagrant/setup-data/bb_username.txt"
BITBUCKET_PASSWORD="/home/vagrant/setup-data/bb_password.txt"

curl -s -XGET "${SERVER}/global/users/admin?password=elita" |jq -r '.message.auth_token[0]' > "${AUTH_FILE}"

#Create BitBucket objects
curl -s -XPUT -H "Auth-Token: $(cat \"${AUTH_FILE}\")" "${SERVER}/global/keypairs?name=kp0&app_name=testapp&key_type=git&from=files" -F "private_key=@/home/vagrant/private.key" -F "public_key=@/home/vagrant/public.key"

curl -s -XPUT -H "Auth-Token: $(cat \"${AUTH_FILE}\")" "${SERVER}/global/gitproviders?name=gp0" -d "{ \"type\": \"bitbucket\", \"auth\": { \"username\": \"$(cat \"${BITBUCKET_USERNAME}\")\", \"password\": \"$(cat \"${BITBUCKET_PASSWORD}\")\" } }"

#Create servers
curl -s -XPUT -H "Auth-Token: $(cat \"${AUTH_FILE}\")" "${SERVER}/server?name=server0&existing=true&environment=test"

curl -s -XPUT -H "Auth-Token: $(cat \"${AUTH_FILE}\")" "${SERVER}/server?name=server1&existing=true&environment=test"

curl -s -XPUT -H "Auth-Token: $(cat \"${AUTH_FILE}\")" "${SERVER}/server?name=server2&existing=true&environment=test"

curl -s -XPUT -H "Auth-Token: $(cat \"${AUTH_FILE}\")" "${SERVER}/server?name=server3&existing=true&environment=test"

#create application endpoints
curl -s -XPUT -H "Auth-Token: $(cat \"${AUTH_FILE}\")" "${SERVER}/app?app_name=testapp"

curl -s -XPUT -H "Auth-Token: $(cat \"${AUTH_FILE}\")" "${SERVER}/app/testapp/gitrepos?name=gr0&existing=false&gitprovider=gp0&keypair=kp0"

curl -s -XPUT -H "Auth-Token: $(cat \"${AUTH_FILE}\")" "${SERVER}/app/testapp/gitdeploys?name=gd0" -d '{ "package": "master", "location": { "path": "/opt/testapp", "gitrepo": "gr0", "default_branch": "master" } }'

curl -s -XPUT -H "Auth-Token: $(cat \"${AUTH_FILE}\")" "${SERVER}/app/testapp/gitdeploys/gd0?initialize=true" -d '{ "servers": [ "server0", "server1", "server2", "server3" ] }'



