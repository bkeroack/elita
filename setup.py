import os

from ez_setup import use_setuptools
use_setuptools()

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.txt')).read()
CHANGES = open(os.path.join(here, 'CHANGES.txt')).read()

requires = [
    'pyramid',
    'gunicorn',
    'gevent',
    'unittest2',
    'pymongo',
    'celery',
    'requests',
    'python-slugify',
    'salt',
    'M2Crypto',
    'PyYAML',
    'lockfile'
    ]

setup(name='daft',
      version="0.76",
      description='daft',
      long_description=README + '\n\n' + CHANGES,
      classifiers=[
        "Programming Language :: Python",
        "Framework :: Pyramid",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        ],
      author='B. Keroack',
      author_email='bkeroack@gmail.com',
      url='',
      keywords='web pylons pyramid deployment automation',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      tests_require=requires,
      test_suite="daft",
      entry_points="""\
      [paste.app_factory]
      main = daft:main
      """,
      )
