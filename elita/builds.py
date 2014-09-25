__author__ = 'bkeroack'

import os
import shutil
import requests
import zipfile
import tarfile
import tempfile
import logging
import glob2
import billiard

import elita.util

class SupportedFileType:
    TarGz = 'tar.gz'
    TarBz2 = 'tar.bz2'
    Zip = 'zip'
    types = [TarBz2, TarGz, Zip]

class UnsupportedFileType(Exception):
    pass

class PackagingError(Exception):
    pass

#async callables
def store_indirect_build(datasvc, app, build, file_type, uri, verify, package_map):
    logging.debug("indirect_upload: downloading from {}".format(uri))
    datasvc.jobsvc.NewJobData({'status': 'Downloading build file from {}'.format(uri)})
    r = requests.get(uri, verify=verify)
    fd, temp_file = tempfile.mkstemp()
    with open(temp_file, 'wb') as f:
        f.write(r.content)
    logging.debug("download and file write complete")
    datasvc.jobsvc.NewJobData({'status': "download and file write complete"})
    return store_uploaded_build(datasvc, app, build, file_type, temp_file, package_map)

def store_uploaded_build(datasvc, app, build, file_type, temp_file, package_map):
    builds_dir = datasvc.settings['elita.builds.dir']
    minimum_build_size = int(datasvc.settings['elita.builds.minimum_size'])
    bs_obj = BuildStorage(builds_dir, app, build, file_type=file_type, input_file=temp_file,
                          size_cutoff=minimum_build_size)
    datasvc.jobsvc.NewJobData({'status': 'validating file size and type'})
    if not bs_obj.validate():
        return {'error': "Invalid file type or corrupted file--check log"}

    datasvc.jobsvc.NewJobData({'status': 'storing file in builds dir'})
    fname = bs_obj.store()

    logging.debug("bs_results: {}".format(fname))

    datasvc.jobsvc.NewJobData({'status': 'updating build packages'})
    build_doc = datasvc.buildsvc.GetBuild(app, build)
    build_doc['master_file'] = fname
    build_doc['packages']['master'] = {'filename': fname, 'file_type': file_type}

    if package_map:
        datasvc.jobsvc.NewJobData({'status': 'applying package map',
                                   'package_map': package_map})
        pm = PackageMapper(fname, file_type, file_type, os.path.dirname(fname), package_map)
        packages = pm.apply()
        pm.cleanup()
        for pkg in packages:
            build_doc['packages'][pkg] = packages[pkg]

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
    datasvc.buildsvc.UpdateBuild(app, build, build_doc)

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
        assert isinstance(size_cutoff, int)
        assert size_cutoff > 0
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
        filesize = os.path.getsize(self.temp_file_name)
        logging.debug("validate_file_size: size_cutoff: {}".format(self.size_cutoff))
        logging.debug("validate_file_size: temp size: {}".format(filesize))
        return filesize >= self.size_cutoff

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


def _threadsafe_apply_package(output_dir, package_name, package, target_type, cwd, q):
    '''
    Executed concurrently in a separate process. Applies a set of patterns to an already-decompressed master package,
    creates package and pushes to output directory

    @type q: billiard.Queue
    '''
    assert elita.util.type_check.is_dictlike(package)
    assert 'patterns' in package
    assert elita.util.type_check.is_seq(package['patterns'])

    patterns = package['patterns']
    prefix = package['prefix'] if 'prefix' in package else None
    remove_prefix = package['remove_prefix'] if 'remove_prefix' in package else None

    def create_new_pkg():
        logging.debug("cwd: {}".format(os.getcwd()))
        if target_type == SupportedFileType.Zip:
            package_fname = "{}.zip".format(package_name)
            package_obj = zipfile.ZipFile(package_fname, 'w')
        elif target_type == SupportedFileType.TarBz2:
            package_fname = "{}.tar.bz2".format(package_name)
            package_obj = tarfile.open(package_fname, mode='w:bz2')
        elif target_type == SupportedFileType.TarGz:
            package_fname = "{}.tar.gz".format(package_name)
            package_obj = tarfile.open(package_fname, mode='w:gz')
        else:
            raise UnsupportedFileType
        return package_obj, package_fname

    def add_file_to_pkg(filename, package_obj):
        assert filename
        arcname = str(filename).replace(remove_prefix, "", 1) if remove_prefix else filename
        arcname = "{}{}".format(prefix, arcname) if prefix else arcname
        if target_type == SupportedFileType.Zip:
            package_obj.write(filename, arcname, zipfile.ZIP_DEFLATED)
        elif target_type == SupportedFileType.TarBz2 or target_type == SupportedFileType.TarGz:
            package_obj.add(filename, arcname=arcname)
        else:
            raise UnsupportedFileType

    def apply_pattern(pattern, package_obj):
        assert pattern and package_obj
        assert elita.util.type_check.is_string(pattern)
        assert package_obj
        logging.debug("applying pattern: {} ({})".format(pattern, package_name))
        files = glob2.glob(pattern)
        if files:
            logging.debug("adding files")
            for f in files:
                add_file_to_pkg(f, package_obj)
        else:
            logging.debug("no files for pattern!")

    os.chdir(cwd)
    po, pfn = create_new_pkg()
    for p in patterns:
        apply_pattern(p, po)
    po.close()
    shutil.move(pfn, "{}/{}".format(output_dir, pfn))
    q.put({package_name: {'file_type': target_type, 'filename': "{}/{}".format(output_dir, pfn)}})


class PackageMapper:
    '''
    Applies supplied package map to the build. Assumes pre-validated package map and a build_dir that exists

    This puts the generated package files directly in the build storage directory and returns a mapping of package
    names to filenames/types (but doesn't update the build object)
    '''
    def __init__(self, master_package_filename, master_file_type, target_file_type, build_dir, package_map):
        assert master_package_filename and master_file_type and target_file_type and build_dir and package_map
        assert elita.util.type_check.is_string(master_package_filename)
        assert elita.util.type_check.is_string(master_file_type)
        assert elita.util.type_check.is_string(target_file_type)
        assert elita.util.type_check.is_string(build_dir)
        assert master_file_type in SupportedFileType.types and target_file_type in SupportedFileType.types
        assert elita.util.type_check.is_dictlike(package_map)
        self.master_pkg = master_package_filename
        self.master_ftype = master_file_type
        self.target_type = target_file_type
        self.build_dir = build_dir
        self.package_map = package_map
        self.temp_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()

        self.package_fname = None  # container for filename
        self.package_obj = None    # container for ZipFile/TarFile objs

    def cleanup(self):
        shutil.rmtree(self.temp_dir)

    def unpack_master_pkg(self):
        '''
        Decompress master package filename to temp location
        '''
        bf = BuildFile({'filename': self.master_pkg, 'file_type': self.master_ftype})
        bf.decompress(self.temp_dir)

    def apply(self):
        '''
        Apply the package map and return a dict of package_names to { 'file_type', 'filename' }
        '''
        self.unpack_master_pkg()

        q = billiard.Queue()
        procs = list()
        for pkg in self.package_map:
            p = billiard.Process(target=_threadsafe_apply_package, name=pkg,
                                 args=(self.build_dir, pkg, self.package_map[pkg], self.target_type, self.temp_dir, q))
            p.start()
            procs.append(p)

        i = 0
        packages = dict()
        while i < len(procs):
            pkg = q.get(150)
            assert pkg and len(pkg) == 1
            pkg_name = pkg.keys()[0]
            packages[pkg_name] = pkg[pkg_name]
            i += 1

        error = False
        for p in procs:
            p.join(150)
            if p.is_alive():
                logging.error("PackageMapper.apply(): timeout waiting for subprocess: {}".format(p.name))
                p.terminate()
                error = True
            if p.exitcode < 0:
                logging.error("PackageMapper.apply(): subprocess killed with signal {}".format(abs(p.exitcode)))
                error = True
            if p.exitcode > 0:
                logging.error("PackageMapper.apply(): subprocess died with exit code {}".format(p.exitcode))
                error = True
        if error:
            raise PackagingError

        return packages




