Development of python-gearman
=============================

These notes are primarily for somebody interested in changing the python-gearman code (whether to submit a patch or create your own fork), not for people who are just using the library.

Running the tests
*****************

The tests are handled by `tox <https://pypi.org/project/tox/>`_, which you can install using pip:

.. code-block::

   pip install tox

You can then run tests by running ``tox``, or specifying a specific task:

.. code-block::

   tox            # run all the tests
   tox -e lint    # run linting
   tox -e py27    # Python 2.7 tests only
   tox -e py36    # Python 3.6 tests only

Tests are also run automatically in Travis on pull requests.

Adding Python 3 compatibility
*****************************

The big change was distinguishing between Unicode strings and byte strings, a distinction which is much stricter in Python 3.
Mostly this meant running the tests, looking for the ``TypeError`` s that got raised, and changing strings to ``u'...'`` or ``b'...'`` as appropriate.

To help with this, I added `coverage <https://github.com/nedbat/coveragepy>`_ to the test suite, so I could find areas of the code the tests wouldn't catch.
I didn't get to 100% coverage, but that's where I'd like to get to!

Submitting patches
******************

The python-gearman release process is heavily based on that of `Hypothesis <https://hypothesis.works/articles/continuous-releases/>`_.

All pull requests should include appropriate tests.

When you've created a pull request that's ready to merge, include a file ``RELEASE.rst`` that describes your change:

.. code-block::

   RELEASE_TYPE: patch

   This release fixes a bug in ``protocol.parse_binary_command()``, where it would fooble the widget instead of wrangling the wotsit.

The RELEASE_TYPE should be one of patch, minor, or major, following `Semantic Versioning <https://semver.org/>`_.

When your pull request is merged to master, our Travis CI build will:

*  Update the version number
*  Add your release note to the changelog
*  Tag a new release on GitHub and commit the new changelog
*  Push a new version to PyPI

Depending on how busy our Travis queue is, this might only take a few minutes!
