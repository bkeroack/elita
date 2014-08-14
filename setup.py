import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.rst')).read()
CHANGES = open(os.path.join(here, 'CHANGES.txt')).read()

requires = [
    #core deps
    'pyramid',
    'gunicorn',
    'gevent',
    'salt',
    'celery',
    'pymongo',

    # direct git integration
    'gitpython>=0.3.2.RC1',

    #for api calls, calculate slugs for BitBucket URLs
    'requests',
    'python-slugify',
    'simplejson',

    # to parse salt states
    'PyYAML',

    # to parse ssh config
    #'paramiko',

    # we need to lock, eg, salt state files during modification
    'lockfile',

    # for installation primarily
    'sh',
    'clint',

    #testing
    'nose',
    'mock'
]

setup(name='elita',
      version="0.59",
      description='Continuous deployment (continuous delivery) and infrastructure management REST framework',
      long_description=README + '\n\n' + CHANGES,
      license='Apache',
      classifiers=[
        "Programming Language :: Python",
        "Framework :: Pyramid",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        "Topic :: System :: Systems Administration",
        "Topic :: Software Development :: Build Tools"
        ],
      author='Benjamen Keroack',
      author_email='ben@elita.io',
      url='https://elita.io/',
      keywords='continuous deployment delivery REST automation devops',
      packages=find_packages(exclude=['test*']),
      package_data={
          'elita_install': ['util/*', '*.ini', '*.txt', '*.rst', '*.cfg'],
          'elita_cli': ['*']
      },
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      entry_points={
          'paste.app_factory': ['main=elita:main'],
          'console_scripts': [
              'elita_install=elita_install:Install',
              'elita=elita_cli:Command_Line_Client'
          ]
      })
