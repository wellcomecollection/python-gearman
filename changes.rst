=========
Changelog
=========

This is a record of all releases of python-gearman3.

------------------
0.2.1 - 2021-06-03
------------------

This release fixes #15, an issue introduced by 595f189 causing pollers to
perform slower because the event registration was not always reflecting the
connection state.

------------------
0.2.0 - 2020-03-01
------------------

More fixes for Python 2/3 compatibility.  Thanks Ross Spencer (@ross-spencer) and Artefactual Systems Inc for this contribution.

------------------
0.1.0 - 2018-12-13
------------------

Initial automatic release of gearman3 on PyPI.

------------------
0.0.0 - 2018-12-13
------------------

A dummy release to populate the initial changelog.

This includes enough changes to get the original python-gearman tests passing
in Python 3.
