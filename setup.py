import os

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
#      package_data={
#          'elita': ['util/*', '*.ini', '*.txt', '*.rst', '*.cfg']
#      },
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
