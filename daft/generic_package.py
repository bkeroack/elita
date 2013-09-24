import logging
import shutil
import tempfile
import os

__author__ = 'bkeroack'

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
