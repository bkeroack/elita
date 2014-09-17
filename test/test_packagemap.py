#requires package_map_data/build-123.*

import os, zipfile, tarfile, os
from elita.builds import PackageMapper, SupportedFileType

BUILD_BASENAME = "package_map_data/build-123"
BUILD_ZIP = "{}.zip".format(BUILD_BASENAME)
BUILD_TGZ = "{}.tar.gz".format(BUILD_BASENAME)
BUILD_TBZ2 = "{}.tar.bz2".format(BUILD_BASENAME)

package_map = {
    "configuration": {
        "patterns": ["build-123/config/**/*"],
        "remove_prefix": "build-123/"
    },
    "binaries": {
        "patterns": ["build-123/bin/**/*"]
    },
    "libraries": {
        "patterns": ["build-123/bin/lib/**/*"]
    },
    "assets": {
        "patterns": ["build-123/assets/**/*"],
        "prefix": "web/static/"
    }
}

def test_packagemap_creates_expected_packages_zip():
    '''
    Test that PackageMapper creates expected packages from master zip
    '''

    cwd = os.getcwd()
    output_dir = "{}/package_map_data/output".format(cwd)
    pm = PackageMapper(BUILD_ZIP, SupportedFileType.Zip, SupportedFileType.Zip, output_dir, package_map)
    pm.apply()
    pm.cleanup()

    expected_output = ['assets.zip', 'configuration.zip', 'binaries.zip', 'libraries.zip']
    files = os.listdir(output_dir)
    assert set(expected_output) == set([f for f in files if f[0] != '.'])   # filter out .keep

    packages = ['configuration.zip', 'binaries.zip', 'libraries.zip', 'assets.zip']
    expected_members = {
        'configuration.zip': ['config/file.yaml', 'config/file.xml', 'config/file.txt'],
        'binaries.zip': ['build-123/bin/lib/', 'build-123/bin/widgets', 'build-123/bin/lib/libfoo.so'],
        'libraries.zip': ['build-123/bin/lib/libfoo.so'],
        'assets.zip': ['web/static/build-123/assets/css/', 'web/static/build-123/assets/css/style.css',
                       'web/static/build-123/assets/main.html', 'web/static/build-123/assets/img/',
                       'web/static/build-123/assets/img/banner.png']
    }

    for p in packages:
        pname = "{}/{}".format(output_dir, p)
        with zipfile.ZipFile(pname, 'r') as zf:
            assert set(zf.namelist()) == set(expected_members[p])
        os.unlink(pname)

def test_packagemap_creates_expected_packages_tgz():
    '''
    Test that PackageMapper creates expected packages from master .tar.gz
    '''

    cwd = os.getcwd()
    output_dir = "{}/package_map_data/output".format(cwd)
    pm = PackageMapper(BUILD_TGZ, SupportedFileType.TarGz, SupportedFileType.TarGz, output_dir, package_map)
    pm.apply()
    pm.cleanup()

    expected_output = ['assets.tar.gz', 'configuration.tar.gz', 'binaries.tar.gz', 'libraries.tar.gz']
    files = os.listdir(output_dir)
    assert set(expected_output) == set([f for f in files if f[0] != '.'])   # filter out .keep

    packages = ['configuration.tar.gz', 'binaries.tar.gz', 'libraries.tar.gz', 'assets.tar.gz']
    # note trailing / removed from empty directories (per tarfile output)
    expected_members = {
        'configuration.tar.gz': ['config/file.yaml', 'config/file.xml', 'config/file.txt'],
        'binaries.tar.gz': ['build-123/bin/lib', 'build-123/bin/widgets', 'build-123/bin/lib/libfoo.so'],
        'libraries.tar.gz': ['build-123/bin/lib/libfoo.so'],
        'assets.tar.gz': ['web/static/build-123/assets/css', 'web/static/build-123/assets/css/style.css',
                       'web/static/build-123/assets/main.html', 'web/static/build-123/assets/img',
                       'web/static/build-123/assets/img/banner.png']
    }

    for p in packages:
        pname = "{}/{}".format(output_dir, p)
        with tarfile.open(pname, 'r:gz') as tf:
            assert set(tf.getnames()) == set(expected_members[p])
        os.unlink(pname)


def test_packagemap_creates_expected_packages_tbz2():
    '''
    Test that PackageMapper creates expected packages from master .tar.bz2
    '''

    cwd = os.getcwd()
    output_dir = "{}/package_map_data/output".format(cwd)
    pm = PackageMapper(BUILD_TBZ2, SupportedFileType.TarBz2, SupportedFileType.TarBz2, output_dir, package_map)
    pm.apply()
    pm.cleanup()

    expected_output = ['assets.tar.bz2', 'configuration.tar.bz2', 'binaries.tar.bz2', 'libraries.tar.bz2']
    files = os.listdir(output_dir)
    assert set(expected_output) == set([f for f in files if f[0] != '.'])   # filter out .keep

    packages = ['configuration.tar.bz2', 'binaries.tar.bz2', 'libraries.tar.bz2', 'assets.tar.bz2']
    # note trailing / removed from empty directories (per tarfile output)
    expected_members = {
        'configuration.tar.bz2': ['config/file.yaml', 'config/file.xml', 'config/file.txt'],
        'binaries.tar.bz2': ['build-123/bin/lib', 'build-123/bin/widgets', 'build-123/bin/lib/libfoo.so'],
        'libraries.tar.bz2': ['build-123/bin/lib/libfoo.so'],
        'assets.tar.bz2': ['web/static/build-123/assets/css', 'web/static/build-123/assets/css/style.css',
                       'web/static/build-123/assets/main.html', 'web/static/build-123/assets/img',
                       'web/static/build-123/assets/img/banner.png']
    }

    for p in packages:
        pname = "{}/{}".format(output_dir, p)
        with tarfile.open(pname, 'r:bz2') as tf:
            assert set(tf.getnames()) == set(expected_members[p])
        os.unlink(pname)
