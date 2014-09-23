============
Introduction
============

Elita is a RESTful deployment engine (Deployment as a Service) for continuous deployment (aka continuous delivery) and
API-driven infrastructure.

At the most basic level, Elita allows you to push build artifacts from a CI server to a specified filesystem location
on end servers. It does this via git and salt, so the deployments are delta compressed and done in parallel across all
the machines.


Why?
----

Deployment scripts are brittle, hard to maintain and difficult to automate. Elita provides generic Deployment as a
Service, allowing deployment to be fully automated behind whatever interface you wish (web application, etc) and without
hard-coding any details regarding infrastructure layout or service providers.

Elita also allows you to create custom endpoints that (when triggered) execute arbitrary Python code. This can be used
to automate any part of infrastructure management (clearing cache, adding/removing servers, etc). Access to endpoints
is controlled by per-user security permissions (same as deployment endpoints).

Technology
----------

Elita is written in `Python <http://www.python.og>`_ (2.7). It uses the `Pyramid web framework
<http://docs.pylonsproject.org/projects/pyramid/en/latest/>`_ with `MongoDB <http://www.mongodb.org>`_ and
`Celery <http://www.celeryproject.org/>`_ for asynchronous jobs.

The design emphasizes asynchronous actions. Any operation that does anything other than pure data modification will be
executed asynchronously in a Celery worker.

The backend uses `salt <http://www.saltstack.org>`_ for remote execution and an external git provider (BitBucket) for
deployment.


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
