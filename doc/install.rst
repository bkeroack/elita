.. _elita-install:

Installation
============


Prerequisites
-------------

* Python 2.7+ (not tested on 3.x)
* salt
* MongoDB
* RabbitMQ (for Celery)
* SWIG (for crypto-related dependencies)
* Python, OpenSSL headers
* git
* nginx (for external access)


Salt
----

Due to technical constraints in salt, you *must* install Elita on the same machine running salt-master. The salt
system should be installed and running with your managed servers (minions) accessible to salt commands.

.. ATTENTION::

   You must ensure that the elita user can run salt commands (the user is created by the installation script).
   The easiest way to do this is to run salt-master as user "elita" and make sure that "elita" is in the
   ``client_acl`` setting in the master config.
   
   You may also need to fix permissions on salt folders:

   .. sourcecode:: bash

      # chown -R elita /etc/salt /var/cache/salt /var/log/salt /var/run/salt
      # chmod 755 /var/cache/salt /var/cache/salt/jobs /var/run/salt

   To test, open a Python interpreter as user elita (or add your user account to group elita, log out and back in) and
   execute the following:

   .. sourcecode:: python

      >>> import salt.client
      >>> sc = salt.client.LocalClient()
      >>> sc.cmd('server01', 'test.ping', [])   # replace 'server01' with a valid minion name


Hardware
--------

Elita makes extensive use of the ``multiprocessing`` module for concurrency (spawning a new Python process for each "thread"),
so memory usage can be substantial with (for example) a large number of servers being controlled, lots of packages, etc.

I've found it runs best with at least 4GB of RAM (on a headless Linux server) with at least two CPU cores.


Ubuntu
------

Installing the non-salt prerequistes on an Ubuntu system:

.. sourcecode:: bash

   $ sudo apt-get update
   $ sudo apt-get install mongodb rabbitmq-server python-pip python-dev libssl-dev swig git nginx


CentOS
------

In general installing on CentOS will be rather painful compared to Ubuntu since very few of the dependencies
are available in the standard yum repositories. You'll need to install them each individually.

First, CentOS 6.x ships with Python 2.6 by default, so you have to `compile and install Python 2.7.x
<http://toomuchdata.com/2014/02/16/how-to-install-python-on-centos/>`_.

After that's complete, install the dependencies listed above, most likely by installing RPMs manually or compiling from scratch.
Once that's finished you should be able to install via the instructions below.

Installation (Linux/POSIX)
--------------------------

After you have all the prerequisites installed and running, do:

.. sourcecode:: bash

   $ sudo pip install elita
   $ sudo elita_install

The script 'elita_install' will move configuration files into their proper places, create the service user/group,
install the init.d script and start Elita.


Testing your Installation
-------------------------

To test that your installation is working correctly, do:

.. sourcecode:: bash

   $ curl -XGET 'http://localhost:2718/?pretty=true'

Elita will listen on port 2718 on localhost only. By convention, external SSL-tunneled access is provided on port 2719.

Administrative User
-------------------

The default admin user has username 'admin' and password 'elita'. You should change this immediately after
verifying your installation before exposing it to the public internet.

.. NOTE::
   The 'admin' user is not treated in any special way, it is just an ordinary user with permissions to access anything.
   You can create an equivalent user (with any name) by giving it the following permissions object:

.. sourcecode:: json

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
permissions, otherwise you could be locked out of your installation. You'll then have to manually hack in a new user
object into MongoDB, and into the root tree, which is not trivial.

Installed Files
---------------

=======================  ==================================================================
File                     Purpose
=======================  ==================================================================
/etc/init.d/elita        Start/stop script
/etc/elita/elita.ini     Pyramid/WSGI and general configuration (MongoDB host, data paths)
/etc/default/elita       Startup options (logs, number of workers, PID files)
/etc/logrotate.d/elita   (optional) Logrotate script
=======================  ==================================================================


Directories
-----------

=====================================================   ================================================================
Path                                                    Purpose
=====================================================   ================================================================
/var/lib/elita                                          Data directory
/var/lib/elita/builds/{app name}                        Builds for an application
/var/lib/elita/builds/{app name}/{build name}           Packages within a build
/var/lib/elita/gitdeploys                               Local working copies of deployment repositories
/var/lib/elita/gitdeploys/{app name}                    Repositories for an application
/var/lib/elita/gitdeploys/{app name}/{gitdeploy name}   Individual repository
/var/log/elita                                          Logs
=====================================================   ================================================================

