Introduction
============

Elita is a framework for API-driven infrastructure. It can be thought of as
middleware between a continuous integration server (such as Teamcity or Bamboo) and the infrastructure that actually
runs the code (production and QA/staging servers, supportin machines, etc.). It uses `salt <http://www.saltstack
.org>`_ remote execution and a plugin architecture to allow custom actions and hook routines.

It can be used to process builds, execute arbitrary setup, provision servers, deploy code (either automatically or
manually) or perform any programmed set of actions.

============
Design Goals
============

* RESTful interface
* Security (user-based with granular permissions)
* Application/Site-agnostic (see below)
* UI independent


========
Security
========

Elita has a robust, granular permissions system which can be used to whitelist/blacklist resources on a per-application
basis.

.. IMPORTANT::
   Due to using stateless authorization tokens, Elita *must* be tunnelled through SSL/TLS. By default, the application listens
   to port 2718 on localhost only. An example nginx.conf for SSL proxying is included.


=======================
Application Agnosticism
=======================

All custom activity is confined to python modules loaded at runtime. Modules register actions and hook callbacks.


===============
UI independence
===============

No UI is required. All functionality can be accessed as intuitively as possible via REST endpoints.

================
salt Interaction
================

Elita uses salt as the remote execution backend but tries hard not to interfere with any existing salt configuration
or states that might be present (for example, it will not interfere with your existing highstates). All
states are stored in a separate subdirectory (by default, something like '/srv/salt/elita').
