from setuptools import setup

setup(name='BayesMAGPIE',
      version='1.0',
      description='XXXs',
      url='https://github.com/MSK-WANGX/BayesMAGPIE',
      author='Xinjun Wang',
      author_email='wangx11@mskcc.org',
      license='MIT',
      packages=['BayesMAGPIE'],
      install_requires=[
          'pandas','numpy','torch', 'pyro'
      ],
      zip_safe=False)
