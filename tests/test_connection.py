# -*- encoding: utf-8

import pytest

from gearman import connection
from gearman.errors import ServerUnavailable


def test_no_host_is_ServerUnavailable():
    with pytest.raises(ServerUnavailable):
        connection.GearmanConnection(host=None)


@pytest.mark.parametrize('keyfile,certfile,ca_certs,expected_use_ssl', [
    (None, None, None, False),
    ('key.txt', None, None, False),
    (None, 'cert.txt', None, False),
    (None, None, 'ca_certs.txt', False),
    ('key.txt', 'cert.txt', None, False),
    (None, 'cert.txt', 'ca_certs.txt', False),
    ('key.txt', None, 'ca_certs.txt', False),
    ('key.txt', 'cert.txt', 'ca_certs.txt', True)
])
def test_use_ssl_only_if_all_three_files(keyfile, certfile, ca_certs, expected_use_ssl):
    conn = connection.GearmanConnection(
        host='localhost',
        keyfile=keyfile,
        certfile=certfile,
        ca_certs=ca_certs
    )
    assert conn.use_ssl == expected_use_ssl
