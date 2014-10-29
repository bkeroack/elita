0.64.0
    - All endpoints now support JSON Patch documents (RFC 6902) for the PATCH verb. This is the only way to (for example)
    remove nested object keys. See docs for details.
    - Added username of triggering user to Deployment object (GET /app/{appname}/deployment/{deployment_id})
    - Internal data layer reorganization, bug fixes