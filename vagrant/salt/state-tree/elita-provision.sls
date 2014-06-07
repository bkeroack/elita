mongodb:
  pkg:
    - installed

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