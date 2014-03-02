====================
Top-Level Containers
====================

The following top-level containers are available:

* ``/app`` - Application container
* ``/global`` - Site-wide global objects (users, tokens, etc.)
* ``/job`` - Asynchronous jobs
* ``/server`` - Server objects

Documentation:

.. toctree::

   app.rst
   global.rst
   job.rst
   server.rst

=================
Common Parameters
=================

The following parameters are available on all endpoints for all verbs:

* ``auth_token``:  Authorization token (required for all resources that don't accept a password URL parameter)
* ``pretty``: Pretty-print JSON response? ("true", "false", "yes", "no")

.. ATTENTION::
   For readability, hostname/port and auth_token parameter are excluded from all example URIs and API calls.
   Keep in mind, every resource requires some form of authentication (auth_token in the majority of cases or password)

================
Case Sensitivity
================

daft URIs are case-sensitive. The following two endpoints are not equivalent:

   ``/app/exampleapp/actions/ScriptedAction``

Contrasted with...

   ``/app/exampleapp/actions/scriptedaction``  Not the same!

.. NOTE::
   URIs are considered case sensitive according to `W3C <http://www.w3.org/TR/WD-html40-970708/htmlweb.html>`_.
   According to `RFC 4343 <http://tools.ietf.org/html/rfc4343>`_, domain names are not case sensitive.
