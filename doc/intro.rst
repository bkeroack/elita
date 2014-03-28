============
Introduction
============

Elita is a framework for continuous deployment (aka continuous delivery) and API-driven infrastructure. It can be
thought of as
middleware between a continuous integration server (such as Jenkins, Teamcity or Bamboo) and the infrastructure that
actually
runs the code (production and QA/staging servers, supporting machines, etc.). It uses `salt <http://www.saltstack
.org>`_ remote execution and a plugin architecture to allow custom actions and hook routines.

.. contents:: Contents

Design Goals
------------

* RESTful
* Flexibility (plugins for hooks/actions)
* Security (user-based with granular permissions)
* Application-agnostic
* UI independent

Flexibility
-----------

Elita exposes hook points and has a "named action" object type which allows plugins to implement custom
routines and code.

Security
--------

Elita has a granular permissions system which can be used to whitelist/blacklist resources on a per-user and
per-application basis.

.. IMPORTANT::
   Due to using stateless authorization tokens, Elita *must* be tunnelled through SSL/TLS. By default, the application listens
   to port 2718 on localhost only.

Application Agnosticism
-----------------------

Built-in functionality is generic and useful for all application types.

UI independence
---------------

No UI is required. All functionality can be accessed via REST endpoints. Endpoints and JSON output are intended to be
automation-friendly to facilitate UI development.

salt Interaction
----------------

Elita uses salt as the remote execution backend but tries hard not to interfere with any existing salt configuration
or states that might be present (for example, it will not interfere with your existing highstates). All
states are stored in a separate subdirectory (by default, something like '/srv/salt/elita').
