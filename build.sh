#!/bin/bash


# python setup.py sdist bdist_wheel
# twine upload dist/* --verbose 


python -m build

python -m twine upload dist/*