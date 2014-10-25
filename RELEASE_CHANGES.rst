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