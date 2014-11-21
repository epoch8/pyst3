#!/usr/bin/env python

from distutils.core import setup

from asterisk import __version__ as version


description = []
f = open('README.rst')

logo_stripped = False
for line in f:
    if not logo_stripped and line.strip():
        continue
    logo_stripped = True
    description.append(line)

licenses = ('Python Software Foundation License',
            'GNU Library or Lesser General Public License (LGPL)')

setup(
    name='pyst3',
    version=version,
    description='A Python 3.x Interface to Asterisk',
    long_description=''.join(description), author='Karl Putland',
    maintainer='Denis Krashnikov',
    maintainer_email='mgpwanderer@gmail.com',
    url='https://github.com/mgpwanderer/pyst3',
    packages=['asterisk'],
    license=', '.join(licenses),
    platforms='Any',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Other Environment',
        'Intended Audience :: Developers',
        'Intended Audience :: Telecommunications Industry',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Topic :: Communications :: Internet Phone',
        'Topic :: Communications :: Telephony',
        'Topic :: Software Development :: Libraries :: Python Modules'
    ] + ['License :: OSI Approved :: ' + l for l in licenses]
)
