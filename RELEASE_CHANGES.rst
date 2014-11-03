0.64.1
    - Deployment list now has optional "details" parameter. If "true", all deployment detail will be included in output.
    - More logging for gitdeploy (de-)initialization.
    - Fixes for JSON patch support.

0.64.0
    - All endpoints now support JSON Patch documents (RFC 6902) for the PATCH verb. This is the only way to (for example)
    remove nested object keys. See docs for details.
    - Added username of triggering user to Deployment object (GET /app/{appname}/deployment/{deployment_id})
    - Internal data layer reorganization, bug fixes