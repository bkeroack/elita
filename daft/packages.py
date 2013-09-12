import tarfile
import zipfile
import tempfile
import os
import shutil
import logging


class PackageProcessingError(Exception):
    pass


class GenericPackage:
    def __init__(self, storage_dir, filename, file_type, build_name):
        logging.debug("GenericPackage: {}, {}, {}, {}".format(storage_dir, filename, file_type, build_name))
        self.storage_dir = storage_dir
        self.filename = filename
        self.file_type = file_type
        self.build_name = build_name
        self.temp_dir_root = tempfile.mkdtemp()
        logging.debug("GenericPackage: self.temp_dir_root: {}".format(self.temp_dir_root))
        self.temp_dir = "{}/{}".format(self.temp_dir_root, self.build_name)
        os.makedirs(self.temp_dir)
        logging.debug("GenericPackage: self.temp_dir: {}".format(self.temp_dir))

    def cleanup(self):
        shutil.rmtree(self.temp_dir_root)


#read file, create packages as temp files.
#return dict { 'config_type': {'filename': fname, 'file_type': file_type}}
#provide cleanup method to delete temp files
class ScoreBig_Packages(GenericPackage):
    def __init__(self, storage_dir, filename, file_type, build_name):
        GenericPackage.__init__(self, storage_dir, filename, file_type, build_name)

    def process(self):
        package, file_type = self.create_teamcity_package()
        return {'teamcity': {'filename': package, 'file_type': file_type}}

    def create_teamcity_package(self):
        self.extract_file()
        self.sbtc = ScoreBig_Package_TeamCity(self.storage_dir, self.temp_dir, self.build_name)
        return self.sbtc.create(), "zip"

    def cleanup(self):
        self.sbtc.cleanup()
        GenericPackage.cleanup(self)

    def extract_file(self):
        with open(self.filename, 'rb') as rf:
            if self.file_type == "tar.gz":
                self.extract_tar('gz', rf)
            elif self.file_type == "tar.bz2":
                self.extract_tar('bz2', rf)
            elif self.file_type == "zip":
                self.extract_zip(rf)

    def extract_tar(self, compression, fd):
        try:
            with tarfile.open(mode='r:{}'.format(compression), fileobj=fd) as tf:
                tf.extractall(self.temp_dir)
        except:
            raise PackageProcessingError("Error decompressing tarfile!")

    def extract_zip(self, fd):
        try:
            with zipfile.ZipFile(fd, 'r') as zf:
                zf.extractall(self.temp_dir)
        except:
            raise PackageProcessingError("Error decompressing zipfile!")

class ScoreBig_Package_TeamCity:
    def __init__(self, storage_dir, directory, build_name):
        logging.debug("ScoreBig_Package_TeamCity: {}, {}, {}".format(storage_dir, directory, build_name))
        self.storage_dir = storage_dir
        self.dir = directory
        self.temp_dir = tempfile.mkdtemp()
        self.build_name = build_name
        self.subpackages = []

    def create(self):
        self.create_subpackages()
        return self.create_monolithic_zip()

    def cleanup(self):
        shutil.rmtree(self.temp_dir)

    def create_subpackages(self):
        self.config_subpackages()
        self.web_subpackage()
        self.functionaltests_subpackage()
        self.scheduledjobs_subpackage()
        self.servicebus_subpackage()
        self.artifacts_subpackage()
        self.assets_subpackage()
        self.migration_subpackage()

    def create_monolithic_zip(self):
        fname = "{}/{}-teamcity.zip".format(self.storage_dir, self.build_name)
        logging.debug("create_monolithic_zip: {}".format(self.subpackages))
        with zipfile.ZipFile(fname, 'a') as zf:
            for f in self.subpackages:
                zf.write(f, os.path.basename(f))
        return fname

    def zipfolder(self, path, zipname, subpath = None):
        with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED) as zf:
            for dirpath, dirs, files in os.walk(path):
                for f in files:
                    bp = str(dirpath).replace(path, "")
                    bp += "" if subpath is None else subpath
                    bp += "/" if bp != "" else ""
                    zf.write(os.path.join(dirpath, f), bp + f)

    def create_subpackage(self, dirname, shortname, subpath):
        path = "{}/{}".format(self.dir, dirname)
        logging.debug("{}_subpackage: {}".format(shortname, path))
        fname = "{}/package-{}-{}.zip".format(self.temp_dir, shortname, self.build_name)
        self.zipfolder(path, fname, subpath=subpath)
        self.subpackages.append(fname)

    def config_subpackages(self):
        path = "{}/Configs".format(self.dir)
        logging.debug("config_subpackages: {}".format(path))
        for d in os.listdir(path):
            subpath = path + '/' + d
            if os.path.isdir(subpath):
                fname = "{}/{}-{}.zip".format(self.temp_dir, d, self.build_name)
                with zipfile.ZipFile(fname, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for f in os.listdir(subpath):
                        subsubpath = subpath + '/' + f
                        if os.path.isfile(subsubpath):
                            zf.write(subsubpath, f)
                            logging.debug("...added file: {}".format(f))
                self.subpackages.append(fname)

    def web_subpackage(self):
        self.create_subpackage("Web-Apps", "web", None)

    def scheduledjobs_subpackage(self):
        self.create_subpackage("Svc-Apps/ScheduledJobs", "scheduledjobs", "scheduledjobsservice")

    def servicebus_subpackage(self):
        self.create_subpackage("Svc-Apps/ServiceBus", "servicebus", "servicebusservice")

    def artifacts_subpackage(self):
        path = "{}/Artifacts".format(self.dir)
        fname = "package-artifacts-{}.zip".format(self.build_name)
        self.zipfolder(path, fname)
        self.subpackages.append(fname)

    def assets_subpackage(self):
        path = "{}/Assets".format(self.dir)
        fname = "package-assets-{}.zip".format(self.build_name)
        self.zipfolder(path, fname)
        self.subpackages.append(fname)

    def functionaltests_subpackage(self):
        #stub - unused package
        fname = "{}/package-functionaltests-{}.zip".format(self.temp_dir, self.build_name)
        open(fname, 'a').close()

    def migration_subpackage(self):
        #stub - unused package
        fname = "{}/package-migration-{}.zip".format(self.temp_dir, self.build_name)
        open(fname, 'a').close()



#hack
PackageApplicationMap = {"scorebig": ScoreBig_Packages}


