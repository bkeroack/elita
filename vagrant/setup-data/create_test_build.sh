#!/bin/sh

cd ~

[ -d ~/deploy_test ] || mkdir ~/deploy_test

echo "$1" > ~/deploy_test/foo.txt
zip ~/${1}.zip ~/deploy_test/*

http PUT "localhost:2718/app/testapp/builds?build_name=${1}-test" "Auth-Token:$(cat ~/auth.txt)"
curl -XPOST -H "Auth-Token:$(cat ~/auth.txt)" -F "build=@./${1}.zip" "http://localhost:2718/app/testapp/builds/${1}-test?file_type=zip&pretty=true"

#echo '{ "servers": [ "server0", "server1", "server2", "server3" ], "gitdeploys": [ "gd0" ] }' |http POST "localhost:2718/app/testapp/deployments?build_name=${1}-test" "Auth-Token:$(cat ~/auth.txt)"



