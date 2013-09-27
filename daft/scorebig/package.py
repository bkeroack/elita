import logging
import tarfile
import zipfile
import tempfile
import os
import shutil
import multiprocessing, Queue

__author__ = 'bkeroack'

from ..generic_package import GenericPackage, PackageProcessingError


#read file, create packages as temp files.
#return dict { 'config_type': {'filename': fname, 'file_type': file_type}}
#provide cleanup method to delete temp files
class ScoreBig_Packages(GenericPackage):
    def __init__(self, storage_dir, filename, file_type, build_name):
        GenericPackage.__init__(self, storage_dir, filename, file_type, build_name)
        self.sbtc = ScoreBig_Package_TeamCity(self.storage_dir, self.temp_dir, self.build_name)

    def process(self):
        tcpkg = self.create_teamcity_package()
        return dict(ScoreBig_Package_SkynetQA(self.sbtc).create().items() + tcpkg.items())

    def create_teamcity_package(self):
        self.extract_file()
        return {'teamcity': {'filename': self.sbtc.create(), 'file_type': 'zip'}}

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


class ScoreBig_Package_SkynetQA:
    def __init__(self, sbtc):
        assert sbtc.__class__.__name__ == "ScoreBig_Package_TeamCity"
        self.subpackages = sbtc.subpackages
        self.storage_dir = sbtc.storage_dir
        self.packages = dict()

    def create(self):
        for f in self.subpackages:
            base_filename = os.path.basename(f)
            new_file = "{}/skynetqa_{}".format(self.storage_dir, base_filename)
            pname = os.path.basename(f).split('-')[1 if "package" in base_filename else 0]
            logging.debug("ScoreBig_Package_SkynetQA: got pname {}".format(pname))
            logging.debug("ScoreBig_Package_SkynetQA: copying {} to {}".format(f, self.storage_dir))
            shutil.copyfile(f, new_file)
            self.packages['skynetqa_{}'.format(pname)] = {'filename': new_file, 'file_type': 'zip'}
        return self.packages


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
        threads = list()
        m = multiprocessing.Manager()
        sp_list = m.list()
        threads.append(multiprocessing.Process(target=self.config_subpackages, args=(sp_list,)))
        threads.append(multiprocessing.Process(target=self.web_subpackage, args=(sp_list,)))
        threads.append(multiprocessing.Process(target=self.functionaltests_subpackage, args=(sp_list,)))
        threads.append(multiprocessing.Process(target=self.scheduledjobs_subpackage, args=(sp_list,)))
        threads.append(multiprocessing.Process(target=self.servicebus_subpackage, args=(sp_list,)))
        threads.append(multiprocessing.Process(target=self.artifacts_subpackage, args=(sp_list,)))
        threads.append(multiprocessing.Process(target=self.assets_subpackage, args=(sp_list,)))
        threads.append(multiprocessing.Process(target=self.migration_subpackage, args=(sp_list,)))
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.subpackages = sp_list

    def create_monolithic_zip(self):
        fname = "{}/teamcity-{}.zip".format(self.storage_dir, self.build_name)
        logging.debug("create_monolithic_zip: {}".format(self.subpackages))
        with zipfile.ZipFile(fname, 'a') as zf:
            for f in self.subpackages:
                zf.write(f, os.path.basename(f))
        return fname

    def zipfolder(self, path, zipname, subpath=None):
        with zipfile.ZipFile(zipname, 'w', zipfile.ZIP_DEFLATED) as zf:
            for dirpath, dirs, files in os.walk(path):
                for f in files:
                    bp = str(dirpath).replace(path, "")
                    bp += "" if subpath is None else subpath
                    bp += bp if bp == "" else "/"
                    zf.write(os.path.join(dirpath, f), bp + f)

    def create_subpackage(self, dirname, shortname, subpath, sp_list):
        path = "{}/{}".format(self.dir, dirname)
        logging.debug("{}_subpackage: {}".format(shortname, path))
        fname = "{}/package-{}-{}.zip".format(self.temp_dir, shortname, self.build_name)
        self.zipfolder(path, fname, subpath=subpath)
        sp_list.append(fname)

    def config_subpackages(self, sp_list):
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
                sp_list.append(fname)

    def web_subpackage(self, sp_list):
        self.create_subpackage("Web-Apps", "web", None, sp_list)

    def scheduledjobs_subpackage(self, sp_list):
        self.create_subpackage("Svc-Apps/ScheduledJobs", "scheduledjobs", "scheduledjobsservice", sp_list)

    def servicebus_subpackage(self, sp_list):
        self.create_subpackage("Svc-Apps/ServiceBus", "servicebus", "servicebusservice", sp_list)

    def artifacts_subpackage(self, sp_list):
        path = "{}/Artifacts".format(self.dir)
        fname = "{}/package-artifacts-{}.zip".format(self.temp_dir, self.build_name)
        self.zipfolder(path, fname)
        sp_list.append(fname)

    def assets_subpackage(self, sp_list):
        path = "{}/Assets".format(self.dir)
        fname = "{}/package-assets-{}.zip".format(self.temp_dir, self.build_name)
        self.zipfolder(path, fname)
        sp_list.append(fname)

    def functionaltests_subpackage(self, sp_list):
        #stub - unused package
        fname = "{}/package-functionaltests-{}.zip".format(self.temp_dir, self.build_name)
        open(fname, 'a').close()

    def migration_subpackage(self, sp_list):
        #stub - unused package
        fname = "{}/package-migration-{}.zip".format(self.temp_dir, self.build_name)
        open(fname, 'a').close()
