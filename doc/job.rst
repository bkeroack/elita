.. _job-endpoints:

=============
Job Endpoints
=============
(only supported verbs are shown for each endpoint)

.. contents:: Contents

Jobs
----

All API endpoints that perform actions (either directly or indirectly) other than pure data model modifications (ie,
object creation/deletion/modification) spawn asynchronous jobs and return immediately with a *job_id*. You can then
query the job container with this job_id to get status information about the job.


View Jobs
^^^^^^^^^

.. http:get::   /job

   :param active: (optional) return only active (non-completed) jobs
   :type active: boolean ["true"/"false"]

   View all available jobs (both current and historical). Pass the optional *active* parameter to restrict the output
   to only currently active jobs. This container requires '_global' permissions to view.

   .. WARNING::
      By default this can produce *a lot* of output.

   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/job?active=true'


View Job
^^^^^^^^

.. http:get::   /job/(string: job_id)

   :param results: (optional) return detailed results from the job rather than a summary
   :type active: boolean ("true"/"false")

   Return information regarding the specified job. If you pass the optional *results* parameter, a running log of job
   progress will be returned as well as summary information. For complex jobs, this can be a substantial amount of output.

   This is a permissionless endpoint (since the job_id is not reasonably guessable).

   **Example request**:

   .. sourcecode:: bash

      $ curl -XGET '/job/ce8e6282-66fe-4b23-a608-968c71711909?results=true'
