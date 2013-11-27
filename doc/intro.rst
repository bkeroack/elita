Introduction
============

daft is a deployment framework intended as middleware between a continuous integration server (such as Teamcity or Bamboo)
and server environment(s). It can be used to process builds, execute arbitrary setup, provision servers and deploy
code (either automatically or manually).

============
* Design Goals
============

* RESTful interface
* Security (users with granular permissions)
* Application-agnostic (see below)
* UI independent


=============
* Application Agnosticism
=============

All custom activity is confined to python modules loaded at runtime. Modules register actions and hook callbacks.


============
* UI independence
============

No UI is required. All functionality can be accessed as intuitively as possible via REST endpoints.

UI development is facilitated through WebSockets.
