============
Introduction
============

Elita is a RESTful framework for continuous deployment (aka continuous delivery) and API-driven infrastructure.


Motivation
----------

When confronted with the task of getting a web application from a CI server to production servers--and doing so in an
automated and repeatable way--I decided not to come up with YASDS (Yet Another Set of Deployment Scripts) but
instead to try to design a general framework that would only have to be written once. If the deployment methodology or server
layout changed it wouldn't have to be thrown out but could be reconfigured or modified instead.

Elita is intended to be as flexible and composable as possible so it can be adapted to the various server topologies,
deployment styles and application frameworks that are out there. The API primitives are chosen in the UNIX philosophy of
simple objects that can be combined in novel ways. In case that isn't enough, Elita also supports plugins
(written according to PyPI conventions) that can hook into various parts of Elita's execution flow or supply complete
custom actions triggered by REST endpoints.

At a basic level, Elita can be thought of as
middleware between a continuous integration server (Jenkins, Teamcity, Bamboo) and the infrastructure that
actually runs the code (production and QA/staging servers, supporting machines, etc.). Elita allows programmatic code
deployment, build (re-)packaging, server provisioning, etc.


Technology
----------

Elita is written in `Python <http://www.python.og>`_ (2.7). It uses the `Pyramid web framework
<http://docs.pylonsproject.org/projects/pyramid/en/latest/>`_ with `MongoDB <http://www.mongodb.org>`_ and
`Celery <http://www.celeryproject.org/>`_ for asynchronous jobs.

The design emphasizes asynchronous actions. Any operation that does anything other than pure data modification will be
executed asynchronously in a Celery worker.

The backend uses `salt <http://www.saltstack.org>`_ for remote execution and an external git provider (BitBucket) for
deployment.

.. contents:: Contents

Design Goals
------------

* RESTful
* Flexibility (plugins for hooks/actions)
* Security (user-based with granular permissions)
* Application-agnostic
* UI independent

Flexibility
^^^^^^^^^^^

Elita exposes hook points and has a "named action" object type which allows plugins to implement custom
routines and code.

Security
^^^^^^^^

Elita has a granular permissions system which can be used to whitelist/blacklist resources on a per-user and
per-application basis.

.. IMPORTANT::
   To be secure, Elita *must* be tunnelled through SSL/TLS. By default, the application listens
   to port 2718 on localhost only.

Application Agnosticism
^^^^^^^^^^^^^^^^^^^^^^^

API functionality is generic and useful for all application types.

UI independence
^^^^^^^^^^^^^^^

No UI is required. All functionality can be accessed via REST endpoints. Endpoints and JSON output are intended to be
automation-friendly to facilitate UI development.

salt Interaction
^^^^^^^^^^^^^^^^

Elita uses salt as the remote execution backend but tries hard not to interfere with any existing salt configuration
or states that might be present (for example, it will not interfere with your existing highstates). All
states are stored in a separate subdirectory (by default, something like '/srv/salt/elita').
