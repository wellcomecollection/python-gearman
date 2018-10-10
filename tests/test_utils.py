# -*- encoding: utf-8

import pytest

from gearman import util


@pytest.mark.parametrize('given_list,expected_result', [
    ([], None),
    ([1], 1),
    (["foo"], "foo")
])
def test_unlist(given_list, expected_result):
    assert util.unlist(given_list) == expected_result


@pytest.mark.parametrize('bad_list', [
    [1, 1, 1],
    [0, 0],
    [None] * 10,
])
def test_passing_longer_list_to_unlist_is_valueerror(bad_list):
    with pytest.raises(ValueError):
        util.unlist(bad_list)
