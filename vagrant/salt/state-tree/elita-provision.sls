mongodb:
  pkg:
    - installed

mongo_config:
  file.replace:
    - name: /etc/mongodb.conf
    - pattern: 127.0.0.1
    - repl: 0.0.0.0
    - require:
      - pkg: mongodb

start_mongo:
  service:
    - name: mongodb
    - running
    - watch:
      - file: mongo_config

rabbitmq-server:
  pkg:
    - installed

python-pip:
  pkg:
    - installed

python-dev:
  pkg:
    - installed

libssl-dev:
  pkg:
    - installed

swig:
  pkg:
    - installed

git:
  pkg:
    - installed

nginx:
  pkg:
    - installed

/etc/nginx/ssl:
  file.directory
    - require:
      - pkg: nginx

/etc/nginx/ssl/cert.pem:
  file.managed:
    - sources:
     - 'salt://nginx/cert.pem'
    - require:
      - file: /etc/nginx/ssl
      - pkg: nginx

/etc/nginx/ssl/cert.key:
  file.managed:
    - sources:
     - 'salt://nginx/cert.key'
     - require:
      - file: /etc/nginx/ssl
      - pkg: nginx