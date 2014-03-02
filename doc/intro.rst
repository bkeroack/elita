Introduction
============

daft (deployment automation framework) is a framework to manage application server environments. It can be thought of as
middleware between a continuous integration server (such as Teamcity or Bamboo) and production and QA/staging servers.

It can be used to process builds, execute arbitrary setup, provision servers, deploy code (either automatically or
manually) or perform any arbitrary programmed set of actions.

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

daft has a robust, granular permissions system which can be used to whitelist/blacklist resources on a per-application
basis.

.. IMPORTANT::
   Due to using stateless authorization tokens, daft *must* be tunnelled through SSL/TLS. By default, the application listens
   to port 2718 on localhost only. An example nginx.conf for SSL proxying is included.


=======================
Application Agnosticism
=======================

All custom activity is confined to python modules loaded at runtime. Modules register actions and hook callbacks.


===============
UI independence
===============

No UI is required. All functionality can be accessed as intuitively as possible via REST endpoints.
