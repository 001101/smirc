#!/usb/bin/python

"""Setup for smirc."""

from setuptools import setup, find_packages

setup(
    name='smirc',
    version="0.0.1",
    description='IRC system monitoring bot',
    url='https://github.com/epiphyte/smirc',
    license='MIT',
    packages=[],
    install_requires=['irc','zmq'],
    entry_points={
        'console_scripts': [
            'smirc=smirc:main'
        ],
    },
)
