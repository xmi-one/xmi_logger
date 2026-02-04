#!/usr/bin/env python
# -*- coding:utf-8 -*-

# Author: gm.zhibo.wang
# E-mail: gm.zhibo.wang@gmail.com
# Date  :
# Desc  :

from setuptools import setup, find_packages
from codecs import open
import glob
import sys
import os


about = {}
here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, "xmi_logger", "__version__.py"), "r", "utf-8") as f:
    exec(f.read(), about)

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name=about["__title__"],
    version=about["__version__"],
    author=about["__author__"],
    author_email=about["__author_email__"],
    description=about["__description__"],
    long_description=long_description,
    long_description_content_type="text/markdown",
    url=about["__url__"],
    license=about.get("__license__", "MIT"),
    packages=find_packages(),
    include_package_data=True,
    python_requires='>=3.8',
    classifiers=[
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        "loguru>=0.7,<1.0",
        "requests>=2.0",
        "aiohttp>=3.8",
    ],
    extras_require={
        "advanced": [
            "psutil>=5.0",
            "cryptography>=3.4",
        ],
    },
    project_urls={
        "Bug Reports": "https://github.com/xmi-one/xmi_logger/issues",
        "Source": "https://github.com/xmi-one/xmi_logger",
    },
)

