#!/bin/bash

# display version, ask to confirm

# do tag
# git tag -s "v${VERSION}" -m "release ${VERSION}"

# remind to rebuild read-the-docs

# rebuild API docs
# pydoctor --make-html --html-output=./doc/apidocs --add-module elita

#push to PyPI
python setup.py sdist upload -r pypi
python setup.py bdist_wheel upload -r pypi
