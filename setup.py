import os

from ez_setup import use_setuptools
use_setuptools()

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.rst')).read()
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
    'lockfile',
    'sh',
    'simplejson',
    'gitpython>=0.3.2.RC1'
    ]

setup(name='elita',
      version="0.79",
      description='Continuous deployment (continuous delivery) and infrastructure management REST framework',
      long_description=README + '\n\n' + CHANGES,
      classifiers=[
        "Programming Language :: Python",
        "Framework :: Pyramid",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        "Topic :: System :: Systems Administration",
        "Topic :: Software Development :: Build Tools",
        "Topic :: Software Development :: Deployment Tools"
        ],
      author='Benjamen Keroack',
      author_email='ben@elita.io',
      url='',
      keywords='continuous deployment delivery REST automation devops',
      packages=find_packages(),
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      tests_require=requires,
      test_suite="elita",
      entry_points="""\
      [paste.app_factory]
      main = elita:main
      """,
      )
