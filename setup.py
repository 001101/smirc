#!/usb/bin/python

"""Setup for smirc."""

from setuptools import setup, find_packages

setup(
    name='smirc',
    version="__VERSION__",
    description='system monitor IRC bot',
    url='https://github.com/epiphyte/smirc',
    license='MIT',
    packages=['smirc'],
    install_requires=['pyzmq', 'irc', 'systemd'],
    entry_points={
        'console_scripts': [
            'smirc = smirc.smirc:main',
        ],
    },
)
