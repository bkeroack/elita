0.63.5
    - Fix authentication for application container endpoint (GET /app):
        * GET - application list will only show applications for which user has at least read permission
        * DELETE - request will succeed iff user has write permission for the requested application
        * PUT - request will succeed iff user has '_global' write permission (admin privileges, essentially)
        * (previously user required '_global' permissions for all verbs)

0.63.4
    - Fix computed user permissions endpoint (applications was blank) (GET /global/users/{username}/permissions)
    - Fix gitdeploy endpoint exception (GET /app/{appname}/gitdeploys/{gitdeploy_name})

0.63.3
    - Don't allow users to change their own permissions

0.63.2
    - Fix ability for admin or other user with admin permissions to view user object endpoints (GET /global/users/{username})
    - Change output format of user endpoint to be consistent with other objects (JSON response has top-level "user" key instead of "message")

0.63.1
    - Allow zero second rolling/ordered deployment pauses. Make zero the default.

0.63.0

    - Add ability to specify different delays between ordered gitdeploy batches and regular batches
    - Add deployment options to Deployment model object (useful for plugins)
    - Show deployment status in deployment list (GET /app/{appname}/deployments)
    - Fix server list in group detail (/app/{appname}/groups/{groupname}) when environment list is specified

0.62.2

    - Clean up changelog

0.62.1

    - Add build name to deployment name/ID
    - Fix user object (and probably other) PATH endpoints
    - Deployment list now is sorted by creation datetime (descending) and includes creation datetime in output (GET /app/{appname}/deployments)
    - Doc fixes

0.62.0

    - Add deployment hook points
    - Add commits object to deployment object

0.61.1

    - Fix authentication bug
    - (internal, affects plugins) Fix issue with missing created_datetime field on documents

0.61.0

    - Implement PATCH verb support for relevant endpoints (docs do not lie anymore)
    - Fix stale root_tree bug
    - Docs update

0.60.2

    - Fix startup script

0.60.1

    - Add glob2 to install dependencies (fixes pip install)
    - Fix exception when not all servers return for git index removal
    - Add salt connectivity check to deployment procedure
    - Execute gunicorn instead of pserve in start script
    - Fix erroneous 'no files' log message in PackageMapper
    - (internal) clean up deployment code a bit

0.60.0

    - Package Map feature: Create build packages automatically on upload from a set of glob patterns (see docs)
    - Delete stale git index locks (if present) during deployment
    - (internal) fix for potential multiprocessing deadlock and better queue usage
    - (internal) New decorator-based parameter validation

0.59.3

    - Fix exceptions in application census
    - Remove application census from top-level application view
    - Small fix to Deployment model
    - Add ordered gitdeploy information to documentation for groups
    - Change repo link, homepage in README
    - Fix docs version, copyright

0.59.2

    - Add documentation links to README

0.59.1

    - Fix issue where gitdeploy ordering was not respected with deployments consisting only of nonrolling groups
    - Consolidate all nonrolling groups into first batch
    - Fix minor bug with deployment result job logging

0.59

    - First public release
