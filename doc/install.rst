Installation
============


Prerequisites
-------------

* MongoDB
* RabbitMQ (for Celery)
* SWIG (for crypto-related dependencies)
* Python, OpenSSL headers
* git


Ubuntu
------

Installing the prerequistes on an Ubuntu system::

    # apt-get update
    # apt-get install mongodb rabbitmq-server python-pip python-dev libssl-dev swig git


Installation (Linux/POSIX)
--------------------------

After you have all the prerequisites installed and running, do::

    # pip install elita
    # elita_install

The first step may take a little while. The script 'elita_install' will move
configuration files into their proper places, create the service user/group, install the init.d script and start Elita.


Testing your Installation
-------------------------

To test that your installation is working correctly, do::

    $ curl -XGET http://localhost:2718/


Configuration Files
-------------------

=======================  ==================================================================
File                     Purpose
=======================  ==================================================================
/etc/elita/elita.ini     Pyramid/WSGI and general configuration (MongoDB host, data paths)
/etc/default/elita       Startup options (logs, number of workers, PID files)
/etc/logrotate.d/elita   (optional) Logrotate script
=======================  ==================================================================
