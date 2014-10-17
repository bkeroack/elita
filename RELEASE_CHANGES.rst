0.63.1
    - Allow zero second rolling/ordered deployment pauses. Make zero the default.

0.63.0

    - Add ability to specify different delays between ordered gitdeploy batches and regular batches
    - Add deployment options to Deployment model object (useful for plugins)
    - Show deployment status in deployment list (GET /app/{appname}/deployments)
    - Fix server list in group detail (/app/{appname}/groups/{groupname}) when environment list is specified