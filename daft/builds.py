__author__ = 'bkeroack'

import os
import logging
import tempfile
import zipfile
import tarfile


class SupportedFileType:
    TarGz = 'tar.gz'
    TarBz2 = 'tar.bz2'
    Zip = 'zip'
    types = [TarBz2, TarGz, Zip]



class BuildError(Exception):
    pass


class BuildStorage:
    def __init__(self, builds_toplevel_dir=None, application=None, name=None, file_type=None, fd=None, size_cutoff=10000000):
        self.builds_toplevel_dir = builds_toplevel_dir
        self.name = name
        self.application = application
        self.file_type = file_type
        self.fd = fd
        self.filename = None
        self.size_cutoff = size_cutoff

        self.write_to_temp()

    def get_temp(self):
        tf = tempfile.mkstemp()
        self.temp_file_name = tf[1]
        self.temp_file = os.fdopen(tf[0], 'wb')

    def write_to_temp(self):
        self.get_temp()
        logging.debug("BuildStorage: write_to_temp: beginning temp file write")
        self.temp_file.write(self.fd.read(-1))
        self.temp_file.close()
        logging.debug("BuildStorage: write_to_temp: finished")
        self.temp_file = open(self.temp_file_name, 'rb')

    def create_storage_dir(self):
        build_dir = "{}{}/{}".format(self.builds_toplevel_dir, self.application, self.name)
        if not os.path.exists(build_dir):
            os.makedirs(build_dir)
        self.storage_dir = build_dir

    def store(self):
        self.create_storage_dir()
        fname = "{}/{}.{}".format(self.storage_dir, self.name, self.file_type)
        with open(self.temp_file_name, 'rb') as tf:
            with open(fname, 'wb') as bf:
                bf.write(tf.read(-1))
        os.remove(self.temp_file_name)
        self.filename = fname
        return self.filename

    def validate_file_size(self):
        return os.path.getsize(self.temp_file_name) >= self.size_cutoff

    def validate(self):
        if not self.validate_file_size():
            return False
        if self.file_type == SupportedFileType.TarGz:
            return self.validate_tgz()
        elif self.file_type == SupportedFileType.TarBz2:
            return self.validate_tbz2()
        elif self.file_type == SupportedFileType.Zip:
            return self.validate_zip()

    def validate_tgz(self):
        return self.validate_tar('gz')

    def validate_tbz2(self):
        return self.validate_tar('bz2')

    def validate_tar(self, compression):
        try:
            with tarfile.open(mode='r:{}'.format(compression), fileobj=self.temp_file) as tf:
                logging.debug("tar.{}: {}, {}, {} members".format(compression, self.application, self.name, len(tf.getnames())))
        except tarfile.ReadError:
            logging.debug("tar.{}: invalid tar file!".format(compression))
            return False
        return True

    def validate_zip(self):
        try:
            with zipfile.ZipFile(self.temp_file, mode='r') as zf:
                logging.debug("zip: {}, {}, {} members".format(self.application, self.name, len(zf.namelist())))
        except zipfile.BadZipfile:
            logging.debug("zip: invalid zip file!")
            return False
        return True


class BuildFile:
    def __init__(self, package_doc):
        self.file_type = package_doc['file_type']
        self.filename = package_doc['filename']

    def decompress(self, target_path):
        if self.file_type == SupportedFileType.Zip:
            self.decompress_zip(target_path)
        elif self.file_type == SupportedFileType.TarBz2:
            self.decompress_tbz2(target_path)
        elif self.file_type == SupportedFileType.TarGz:
            self.decompress_tgz(target_path)
        else:
            raise BuildError

    def decompress_tar(self, target_path, ext):
        with tarfile.open(name=self.filename, mode='r:{}'.format(ext)) as tf:
            tf.extractall(target_path)

    def decompress_tbz2(self, target_path):
        self.decompress_tar(target_path, 'bz2')

    def decompress_tgz(self, target_path):
        self.decompress_tar(target_path, 'gz')

    def decompress_zip(self, target_path):
        with zipfile.ZipFile(self.filename, 'r') as zf:
            zf.extractall(target_path)



