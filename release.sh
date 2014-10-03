#!/bin/bash

# display version, ask to confirm

# do tag

# remind to rebuild docs

#push to PyPI
python setup.py sdist upload -r pypi
python setup.py bdist_wheel upload -r pypi
