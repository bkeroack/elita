import tarfile
import zipfile
import tempfile
import os
import shutil
import logging

class PackageProcessingError(Exception):
    pass

class GenericPackage:
    def __init__(self, filename, file_type, build_name):
        self.filename = filename
        self.file_type = file_type
        self.build_name = build_name
        self.temp_dir_root = tempfile.mkdtemp()
        self.temp_dir = os.makedirs("{}/{}".format(self.temp_dir_root, self.build_name))

    def cleanup(self):
        shutil.rmtree(self.temp_dir_root)


#read file, create packages as temp files.
#return dict { 'config_type': file_object }
#provide cleanup method to delete temp files
class ScoreBig_Packages(GenericPackage):
    def process(self):
        return self.create_teamcity_package()

    def create_teamcity_package(self):
        self.extract_file()

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
    def __init__(self, directory, root_dir, build_name):
        self.dir = directory
        self.temp_dir = tempfile.mkdtemp(dir=root_dir)
        self.build_name = build_name

    def create(self):
        self.config_subpackages()
        self.web_subpackage()
        self.functionaltests_subpackage()
        self.scheduledjobs_subpackage()
        self.servicebus_subpackage()
        self.artifacts_subpackage()
        self.assets_subpackage()
        self.migration_subpackage()

    def config_subpackages(self):
        path = "{}/Configs".format(self.dir)
        logging.debug("config_subpackages: {}".format(path))
        for d in os.listdir(path):
            subpath = path + '/' + d
            if os.path.isdir(subpath):
                fname = "{}-{}.zip".format(d, self.build_name)
                with zipfile.ZipFile(fname, 'w') as zf:
                    for f in os.listdir(subpath):
                        subsubpath = subpath + '/' + f
                        if os.path.isfile(subsubpath):
                            zf.write(subsubpath, f)
                            logging.debug("...added file: {}".format(f))

    def web_subpackage(self):
        path = "{}/Web-Apps"


