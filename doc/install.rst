Installation
============


Prerequisites
-------------

* Python 2.7+ (not tested on 3.x)
* MongoDB
* RabbitMQ (for Celery)
* SWIG (for crypto-related dependencies)
* Python, OpenSSL headers
* git
* nginx (for external access)


Ubuntu
------

Installing the prerequistes on an Ubuntu system::

    # apt-get update
    # apt-get install mongodb rabbitmq-server python-pip python-dev libssl-dev swig git nginx


CentOS
------

In general installing on CentOS will be somewhat painful compared to Ubuntu, since very few of the dependencies
are available in the standard yum repositories. You'll need to install them each individually.

First, CentOS 6.x ships with Python 2.6 by default, so you have to `compile and install Python 2.7.x
<http://toomuchdata.com/2014/02/16/how-to-install-python-on-centos/>`_ first.

After that's complete, install the dependencies listed above, probably by installing RPMs manually or compiling from scratch.
Once that's finished you should be able to install via the instructions below.

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

    $ curl -XGET 'http://localhost:2718/?pretty=true'


Administrative User
-------------------

The default admin user has username 'admin' and password 'elita'. You should change this immediately after
verifying your installation before exposing it to the public internet.

.. NOTE::
   The 'admin' user is not treated in any special way, it is just an ordinary user with permissions to access anything.
   You can create an equivalent user (with any name) by giving it the following permissions object::

       {
          "apps": {
             "*": "read/write",
             "_global": "read/write"
          },
          "actions": {
             "*": {
                "*": "execute"
             }
          },
          "servers": [ "*" ]
       }

   Just be sure that if you change the permissions on 'admin' (or delete it) that you have a different user with full
   permissions, otherwise you could be locked out of your installation.

Configuration Files
-------------------

=======================  ==================================================================
File                     Purpose
=======================  ==================================================================
/etc/elita/elita.ini     Pyramid/WSGI and general configuration (MongoDB host, data paths)
/etc/default/elita       Startup options (logs, number of workers, PID files)
/etc/logrotate.d/elita   (optional) Logrotate script
=======================  ==================================================================
