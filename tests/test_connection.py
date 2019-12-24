# -*- encoding: utf-8

import pytest

from gearman import connection, compat
from gearman.errors import ConnectionError, ServerUnavailable
from gearman.protocol import GEARMAN_COMMAND_TEXT_COMMAND, GEARMAN_COMMAND_ECHO_REQ


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


def test_no_socket_means_no_fileno():
    conn = connection.GearmanConnection(host='localhost')
    with pytest.raises(ConnectionError, match='no socket set'):
        conn.fileno()


def test_send_commands_to_buffer():
    conn = connection.GearmanConnection(host='localhost')
    assert conn.send_commands_to_buffer() is None
    assert conn._outgoing_buffer == b''
    conn._outgoing_commands.append((GEARMAN_COMMAND_ECHO_REQ, {"data": "test"}))
    conn.send_commands_to_buffer()
    assert conn._outgoing_buffer == b"\x00REQ\x00\x00\x00\x10\x00\x00\x00\x04test"
    if compat.PY3:
        assert isinstance(conn._outgoing_buffer, compat.binary_type)
    else:
        assert isinstance(conn._outgoing_buffer, compat.binary_type)
    conn._reset_connection()
    conn._outgoing_commands.append((GEARMAN_COMMAND_TEXT_COMMAND, {"raw_text": "raw---text"}))
    conn.send_commands_to_buffer()
    assert conn._outgoing_buffer == b"raw---text"
    if compat.PY3:
        assert isinstance(conn._outgoing_buffer, compat.binary_type)
    else:
        assert isinstance(conn._outgoing_buffer, compat.binary_type)
