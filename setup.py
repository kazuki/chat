from distutils.core import setup
setup(
    name = 'chat',
    packages = ['chat'],
    version = '0.0.1',
    license = 'GNU GPLv3',
    long_description=open('README.md').read(),
    package_data = {
        'chat': ['static/*.*',
                 'static/js/*.*',
                 'static/css/*.*',
                 'static/css/*/*.*',
                 'static/css/*/*/*.*',
                 'static/img/*.*',
                 'templates/*.*']
    }
)
