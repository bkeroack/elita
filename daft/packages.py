import scorebig


PackageApplicationMap = dict()


class RegisterPackages:
    def __init__(self):
        self.modules = [scorebig]

    def register(self):
        global PackageApplicationMap
        for m in self.modules:
            apps = m.register_apps()
            for a in apps:
                PackageApplicationMap[a] = m.register_package()
