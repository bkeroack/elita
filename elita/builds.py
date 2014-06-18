__author__ = 'bkeroack'

import os
import shutil
import requests
import zipfile
import tarfile
import tempfile
import logging

import elita.util

class SupportedFileType:
    TarGz = 'tar.gz'
    TarBz2 = 'tar.bz2'
    Zip = 'zip'
    types = [TarBz2, TarGz, Zip]

#async callables
def store_indirect_build(datasvc, app, build, file_type, uri, verify):
    logging.debug("indirect_upload: downloading from {}".format(uri))
    datasvc.jobsvc.NewJobData({'status': 'Downloading build file from {}'.format(uri)})
    r = requests.get(uri, verify=verify)
    fd, temp_file = tempfile.mkstemp()
    with open(temp_file, 'wb') as f:
        f.write(r.content)
    logging.debug("download and file write complete")
    datasvc.jobsvc.NewJobData({'status': "download and file write complete"})
    return store_uploaded_build(datasvc, app, build, file_type, temp_file)

def store_uploaded_build(datasvc, app, build, file_type, temp_file):
    builds_dir = datasvc.settings['elita.builds.dir']
    bs_obj = BuildStorage(builds_dir, app, build, file_type=file_type, input_file=temp_file)
    datasvc.jobsvc.NewJobData({'status': 'validating file size and type'})
    if not bs_obj.validate():
        return {'error': "Invalid file type or corrupted file--check log"}

    datasvc.jobsvc.NewJobData({'status': 'storing file in builds dir'})
    fname = bs_obj.store()

    logging.debug("bs_results: {}".format(fname))

    datasvc.jobsvc.NewJobData({'status': 'updating build packages'})
    build_doc = datasvc.buildsvc.GetBuildDoc(app, build)
    build_doc['master_file'] = fname
    build_doc['packages']['master'] = {'filename': fname, 'file_type': file_type}

    for k in build_doc['packages']:
        fname = build_doc['packages'][k]['filename']
        ftype = build_doc['packages'][k]['file_type']
        found = False
        for f in build_doc['files']:
            if f['path'] == fname:
                found = True
        if not found:
            build_doc['files'].append({"file_type": ftype, "path": fname})
    build_doc['stored'] = True
    logging.debug("packages: {}".format(build_doc['packages'].keys()))
    datasvc.buildsvc.UpdateBuild(app, build_doc)

    datasvc.jobsvc.NewJobData({'status': 'running hook BUILD_UPLOAD_SUCCESS'})
    args = {
        'hook_parameters':
            {
                'build_name': build,
                'build_storage_info':
                    {
                      'storage_dir': bs_obj.storage_dir,
                      'filename': build_doc['master_file'],
                      'file_type': file_type
                    }
            }
    }
    res = datasvc.actionsvc.hooks.run_hook(app, 'BUILD_UPLOAD_SUCCESS', args)

    return {
        "build_stored": {
            "application": app,
            "build_name": build,
            "actions_result": res
        }
    }


class BuildError(Exception):
    pass


class BuildStorage:
    __metaclass__ = elita.util.LoggingMetaClass
    
    def __init__(self, builds_toplevel_dir=None, application=None, name=None, file_type=None, input_file=None,
                 size_cutoff=1000000):
        self.builds_toplevel_dir = builds_toplevel_dir
        self.name = name
        self.application = application
        self.file_type = file_type
        self.temp_file_name = input_file
        self.size_cutoff = size_cutoff


    def create_storage_dir(self):
        build_dir = "{}{}/{}".format(self.builds_toplevel_dir, self.application, self.name)
        if not os.path.exists(build_dir):
            os.makedirs(build_dir)
        self.storage_dir = build_dir

    def store(self):
        self.create_storage_dir()
        fname = "{}/{}.{}".format(self.storage_dir, self.name, self.file_type)
        shutil.copy(self.temp_file_name, fname)
        os.remove(self.temp_file_name)
        return fname

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
            with tarfile.open(name=self.temp_file_name, mode='r:{}'.format(compression)) as tf:
                logging.debug("tar.{}: {}, {}, {} members".format(compression, self.application, self.name,
                                                                        len(tf.getnames())))
        except tarfile.ReadError:
            logging.debug("tar.{}: invalid tar file!".format(compression))
            return False
        return True

    def validate_zip(self):
        try:
            with zipfile.ZipFile(self.temp_file_name, mode='r') as zf:
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



