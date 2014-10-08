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
