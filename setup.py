from setuptools import setup, find_packages

exec(open('ipbb/_version.py').read())

setup(
    name='ipbb',
    version=__version__,
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'Click',
        'Click-didyoumean',
        'TextTable',
        'Sh',
        'Pexpect',
        'PsUtil'
    ],
    entry_points='''
        [console_scripts]
        ipbb=ipbb.scripts.builder:main
        ipb-prog=ipbb.scripts.programmer:main
    ''',
)