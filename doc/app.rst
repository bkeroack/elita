=====================
Application Endpoints
=====================
(only supported verbs are shown for each endpoint)

.. contents:: Contents

Applications
------------

.. http:get::   /app

   Returns terse list of applications


   **Example request**:

   .. sourcecode:: http

      $ curl -XGET '/app'

.. http:put::   /app

   :param app_name: application name
   :type app_name: string

   Create a new application.


   **Example request**:

   .. sourcecode:: http

      $ curl -XPUT '/app?app_name=widgetmaker'

.. http:delete::   /app/(string: app_name)

   Remove an application.

   .. WARNING::
      This will also delete all data associated with that application. This cannot be undone.

   **Example request**:

   .. sourcecode:: http

      $ curl -XDELETE '/app/widgetmaker'


Builds
------

.. http:get::   /app/(string: app_name)/builds

   Returns list of all application builds.


   **Example request**:

   .. sourcecode:: http

      $ curl -XGET '/app/widgetmaker/builds'


.. http:put::   /app/(string: app_name)/builds

   :param build_name: build name
   :jsonparam string body: JSON object containing optional attributes
   :type build_name: string

   Create a new build object.

   **Example request**:

   .. sourcecode:: http

      $ curl -XPUT '/app/widgetmakers/builds?build_name=1-master' -d '{ "attributes": { "branch_name": "master" } }'

.. http:patch::   /app/(string: app_name)/builds/(string: build_name)

   :jsonparam string body: JSON object containing optional attributes to modify

   Modify the attributes of a build object.

   .. NOTE::
      Attributes is the only valid key to modify. The provided attributes attribute will replace whatever is
      currently on the build object.

   **Example request**:

   .. sourcecode:: http

      $ curl -XPATCH '/app/widgetmakers/builds/1-master' -d '{ "attributes": { "branch_name": "something-else" } }'

.. http:delete::   /app/(string: app_name)/builds/(string: build_name)

   Remove a new build object.

   **Example request**:

   .. sourcecode:: http

      $ curl -XDELETE '/app/widgetmakers/builds/1-master'

.. http:post::   /app/(string: app_name)/builds/(string: build_name)

   :param file_type: file type (either "zip", "tar.gz" or "tar.bz2")
   :param indirect_url: URL-encoded location to download the build from (optional, only for indirect uploads)
   :formparameter file: File data (optional, only if indirect_url isn't specified)

   Upload a build. This can be done either directly by including file data in a form post,
   or indirectly by providing a URL-encoded location that elita can download the build from.

   .. NOTE::
      If indirect_url is provided it will always be used, even if the form parameter file is also provided in the
      same request.

   **Example request (direct)**:

   .. sourcecode:: http

      $ curl -XPOST '/app/widgetmakers/builds/1-master?file_type=zip' -F "file=@/home/user/build.zip"

   **Example request (indirect)**:

   .. sourcecode:: http

      # indirect upload from http://foobar.com/build.zip
      $ curl -XPOST '/app/widgetmakers/builds/1-master?file_type=zip&indirect_url=http%3A%2F%2Ffoobar.com%2Fbuild.zip'



