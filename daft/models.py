from persistent.mapping import PersistentMapping

# URL model:
# root/app/
# root/app/{app_name}/builds/
# root/app/{app_name}/builds/{build_name}
# root/app/{app_name}/environments/
# root/app/{app_name}/environments/{env_name}/deployments
# root/app/{app_name}/environments/{env_name}/deployments/{deployment_id}
# root/app/{app_name}/environments/{env_name}/servers
# root/app/{app_name}/environemnt/{env_name}/servers/{server_name}


class SupportedFileType:
    TarGz = 'tar.gz'
    TarBz2 = 'tar.bz2'
    Zip = 'zip'
    types = [TarBz2, TarGz, Zip]

class Server:
    env_name = None

class Deployment:
    env_name = None

class Environment:
    app_name = None

class EnvironmentContainer(PersistentMapping):
    def __init__(self, app_name):
        PersistentMapping.__init__(self)
        self.app_name = app_name

class Build(PersistentMapping):
    def __init__(self, app_name, build_name):
        PersistentMapping.__init__(self)
        self.app_name = app_name
        self.build_name = build_name
        self.stored = False
        self.files = dict()  # { filename: filetype }
        self.master_file = None  # original uploaded file

class BuildContainer(PersistentMapping):
    def __init__(self, app_name):
        PersistentMapping.__init__(self)
        self.app_name = app_name

class Application(PersistentMapping):
    def __init__(self, app_name):
        PersistentMapping.__init__(self)
        self.app_name = app_name

class ApplicationContainer(PersistentMapping):
    pass

class RootApplication(PersistentMapping):
    pass


def appmaker(zodb_root):
    if not 'app_root' in zodb_root:
        app_root = RootApplication()
        zodb_root['app_root'] = app_root
        zodb_root['app_root']['app'] = ApplicationContainer()
        import transaction
        transaction.commit()
    return zodb_root['app_root']
