# -*- encoding: utf-8

from hypothesis import given
from hypothesis.strategies import sampled_from, sets
import pytest

from gearman.admin_client import GearmanAdminClient, ECHO_STRING
from gearman.admin_client_handler import GearmanAdminClientCommandHandler
from gearman.connection import GearmanConnection
from gearman.errors import GearmanError, InvalidAdminClientState, ProtocolError
from gearman.protocol import (
    GEARMAN_COMMAND_ECHO_RES,
    GEARMAN_COMMAND_ECHO_REQ,
    GEARMAN_SERVER_COMMAND_CANCEL_JOB,
    GEARMAN_SERVER_COMMAND_GETPID,
    GEARMAN_SERVER_COMMAND_SHOW_JOBS,
    GEARMAN_SERVER_COMMAND_SHOW_UNIQUE_JOBS,
    GEARMAN_COMMAND_TEXT_COMMAND,
    GEARMAN_SERVER_COMMAND_STATUS, GEARMAN_SERVER_COMMAND_VERSION, GEARMAN_SERVER_COMMAND_WORKERS, GEARMAN_SERVER_COMMAND_MAXQUEUE, GEARMAN_SERVER_COMMAND_SHUTDOWN)

from tests._core_testing import _GearmanAbstractTest, MockGearmanConnectionManager


class MockGearmanAdminClient(GearmanAdminClient, MockGearmanConnectionManager):
    pass


class _StateMachineTest(_GearmanAbstractTest):

    connection_manager_class = MockGearmanAdminClient

    def setUp(self):
        super(_StateMachineTest, self).setUp()
        self.connection_manager.current_connection = self.connection
        self.connection_manager.current_handler = self.command_handler

    def send_server_command(self, expected_command):
        self.command_handler.send_text_command(expected_command)
        expected_line = "%s\n" % expected_command
        self.assert_sent_command(GEARMAN_COMMAND_TEXT_COMMAND, raw_text=expected_line)

        assert self.command_handler._sent_commands[0] == expected_command

    def recv_server_response(self, response_line):
        self.command_handler.recv_command(GEARMAN_COMMAND_TEXT_COMMAND, raw_text=response_line)

    def pop_response(self, expected_command):
        server_cmd, server_response = self.command_handler.pop_response()
        assert expected_command == server_cmd

        return server_response


class CommandHandlerStateMachineTest(_StateMachineTest):
    """Test the public interface a GearmanWorker may need to call in order to update state on a GearmanWorkerCommandHandler"""
    command_handler_class = GearmanAdminClientCommandHandler

    def test_send_illegal_server_commands(self):
        with pytest.raises(ProtocolError):
            self.send_server_command("This is not a server command")

    def test_ping_server(self):
        self.command_handler.send_echo_request(ECHO_STRING)
        self.assert_sent_command(GEARMAN_COMMAND_ECHO_REQ, data=ECHO_STRING)
        assert self.command_handler._sent_commands[0] == GEARMAN_COMMAND_ECHO_REQ

        self.command_handler.recv_command(GEARMAN_COMMAND_ECHO_RES, data=ECHO_STRING)
        server_response = self.pop_response(GEARMAN_COMMAND_ECHO_REQ)
        assert server_response == ECHO_STRING

    def test_state_and_protocol_errors_for_status(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_STATUS)

        # Test premature popping as this we aren't until ready we see the '.'
        with pytest.raises(InvalidAdminClientState):
            self.pop_response(GEARMAN_SERVER_COMMAND_STATUS)

        # Test malformed server status
        with pytest.raises(ProtocolError):
            self.recv_server_response('\t'.join(['12', 'IP-A', 'CLIENT-A']))

        self.recv_server_response('.')

        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_STATUS)
        assert server_response == ()

    def test_response_ready(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_STATUS)

        # We aren't ready until we see the '.'
        assert not self.command_handler.response_ready

        self.recv_server_response(".")
        assert self.command_handler.response_ready

    def test_multiple_status(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_STATUS)
        self.recv_server_response('\t'.join(['test_function', '1', '5', '17']))
        self.recv_server_response('\t'.join(['another_function', '2', '4', '23']))
        self.recv_server_response('.')

        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_STATUS)
        assert len(server_response) == 2

        test_response, another_response = server_response
        assert test_response['task'] == 'test_function'
        assert test_response['queued'] == 1
        assert test_response['running'] == 5
        assert test_response['workers'] == 17

        assert another_response['task'] == 'another_function'
        assert another_response['queued'] == 2
        assert another_response['running'] == 4
        assert another_response['workers'] == 23

    def test_version(self):
        expected_version = '0.12345'

        self.send_server_command(GEARMAN_SERVER_COMMAND_VERSION)
        self.recv_server_response(expected_version)

        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_VERSION)
        assert expected_version == server_response

    def test_state_and_protocol_errors_for_workers(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_WORKERS)

        # Test premature popping as this we aren't until ready we see the '.'
        with pytest.raises(InvalidAdminClientState):
            self.pop_response(GEARMAN_SERVER_COMMAND_WORKERS)

        # Test malformed responses
        with pytest.raises(ProtocolError):
            self.recv_server_response(' '.join(['12', 'IP-A', 'CLIENT-A']))

        with pytest.raises(ProtocolError):
            self.recv_server_response(' '.join(['12', 'IP-A', 'CLIENT-A', 'NOT:']))

        self.recv_server_response('.')

        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_WORKERS)
        assert server_response == ()

    def test_multiple_workers(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_WORKERS)
        self.recv_server_response(' '.join(['12', 'IP-A', 'CLIENT-A', ':', 'function-A', 'function-B']))
        self.recv_server_response(' '.join(['13', 'IP-B', 'CLIENT-B', ':', 'function-C']))
        self.recv_server_response('.')

        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_WORKERS)
        assert len(server_response) == 2

        test_response, another_response = server_response
        assert test_response['file_descriptor'] == '12'
        assert test_response['ip'] == 'IP-A'
        assert test_response['client_id'] == 'CLIENT-A'
        assert test_response['tasks'] == ('function-A', 'function-B')

        assert another_response['file_descriptor'] == '13'
        assert another_response['ip'] == 'IP-B'
        assert another_response['client_id'] == 'CLIENT-B'
        assert another_response['tasks'] == ('function-C', )

    def test_maxqueue(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_MAXQUEUE)
        with pytest.raises(ProtocolError):
            self.recv_server_response('NOT OK')

        # Pop prematurely
        with pytest.raises(InvalidAdminClientState):
            self.pop_response(GEARMAN_SERVER_COMMAND_MAXQUEUE)

        self.recv_server_response('OK')
        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_MAXQUEUE)
        assert server_response == 'OK'

    def test_shutdown(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_SHUTDOWN)

        # Pop prematurely
        with pytest.raises(InvalidAdminClientState):
            self.pop_response(GEARMAN_SERVER_COMMAND_SHUTDOWN)

        self.recv_server_response(None)
        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_SHUTDOWN)
        assert server_response is None

    def test_getpid(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_GETPID)

        # Pop prematurely
        with pytest.raises(InvalidAdminClientState):
            self.pop_response(GEARMAN_SERVER_COMMAND_GETPID)

        self.recv_server_response(None)
        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_GETPID)
        assert server_response is None

    def test_cancel_job(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_CANCEL_JOB)

        # Pop prematurely
        with pytest.raises(InvalidAdminClientState):
            self.pop_response(GEARMAN_SERVER_COMMAND_CANCEL_JOB)

        self.recv_server_response(None)
        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_CANCEL_JOB)
        assert server_response is None

    def test_show_jobs_empty(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_SHOW_JOBS)

        # Pop prematurely
        with pytest.raises(InvalidAdminClientState):
            self.pop_response(GEARMAN_SERVER_COMMAND_SHOW_JOBS)

        self.recv_server_response('.')
        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_SHOW_JOBS)
        assert server_response == ()

    def test_show_jobs_incorrect_tokens(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_SHOW_JOBS)

        with pytest.raises(ProtocolError, match="Received 3 tokens, expected 4 tokens"):
            self.recv_server_response('1\t2\t3')

    def test_show_jobs(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_SHOW_JOBS)

        self.recv_server_response('foo\t1\t2\t3')
        self.recv_server_response('bar\t4\t5\t6')

        # Pop prematurely
        with pytest.raises(InvalidAdminClientState):
            self.pop_response(GEARMAN_SERVER_COMMAND_SHOW_JOBS)

        self.recv_server_response(".")
        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_SHOW_JOBS)
        assert server_response == (
            {"handle": "foo", "queued": 1, "canceled": 2, "enabled": 3},
            {"handle": "bar", "queued": 4, "canceled": 5, "enabled": 6},
        )

    def test_show_unique_jobs_empty(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_SHOW_UNIQUE_JOBS)

        self.recv_server_response('.')
        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_SHOW_UNIQUE_JOBS)
        assert server_response == ()

    def test_show_unique_jobs_incorrect_tokens(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_SHOW_UNIQUE_JOBS)

        with pytest.raises(ProtocolError, match="Received 3 tokens, expected 1 tokens"):
            self.recv_server_response('1\t2\t3')

    def test_show_unique_jobs(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_SHOW_UNIQUE_JOBS)

        self.recv_server_response('foo')
        self.recv_server_response('bar')

        self.recv_server_response(".")
        server_response = self.pop_response(GEARMAN_SERVER_COMMAND_SHOW_UNIQUE_JOBS)
        assert server_response == (
            {"unique": ["foo"]},
            {"unique": ["bar"]},
        )

    def test_recv_server_response_without_command(self):
        with pytest.raises(InvalidAdminClientState, match='Received an unexpected server response'):
            self.recv_server_response(b'123')


def _assert_gearman_connection_equal(conn1, conn2):
    # There's currently no equality method defined on ``GearmanConnection``,
    # so separate instances are unequal.
    #
    # Adding an equality method has a bunch of other subtle side effects
    # (e.g. related to hashing), so making this method test-only is safer
    # until we have better test coverage.
    #
    assert isinstance(conn1, GearmanConnection)
    assert isinstance(conn2, GearmanConnection)
    assert conn1.gearman_host == conn2.gearman_host
    assert conn1.gearman_port == conn2.gearman_port
    assert conn1.keyfile == conn2.keyfile
    assert conn1.certfile == conn2.certfile
    assert conn1.ca_certs == conn2.ca_certs


class TestGearmanAdminClient(object):

    @pytest.mark.parametrize('host_config', [
        # As a string specifying a port
        "localhost:4730",

        # If a port isn't specified, we use the default port
        "localhost",

        # As a tuple (with and without int argument)
        ("localhost", "4730"),
        ("localhost", 4730),
    ])
    def test_creating_with_host_port_pair_str(self, host_config):
        client = GearmanAdminClient(host_list=[host_config])
        assert len(client.connection_list) == 1

        _assert_gearman_connection_equal(
            conn1=GearmanConnection(host="localhost", port=4730),
            conn2=client.connection_list[0]
        )

    def test_multiple_hosts_is_error(self):
        with pytest.raises(GearmanError, match="Only pass a single host"):
            GearmanAdminClient(host_list=[
                "localhost:1234",
                "example.org:5678",
            ])

    @given(sets(
        sampled_from(['host', 'port', 'keyfile', 'certfile', 'ca_certs']),
        min_size=1))
    def test_passing_incomplete_ssl_data_is_error(self, keys_to_delete):
        host_config = {
            "host": "localhost",
            "port": 5000,
            "keyfile": "key.txt",
            "certfile": "cert.txt",
            "ca_certs": "ca_certs.txt",
        }

        for key in keys_to_delete:
            del host_config[key]

        with pytest.raises(GearmanError, match="Incomplete SSL connection definition"):
            GearmanAdminClient(host_list=[host_config])

    @pytest.mark.parametrize('bad_config', [None, 1, object])
    def test_passing_bad_host_config_is_error(self, bad_config):
        with pytest.raises(GearmanError, match="Expected str, tuple or dict"):
            GearmanAdminClient(host_list=[bad_config])

    def test_creating_with_ssl_host(self):
        host_config = {
            "host": "localhost",
            "port": 5000,
            "keyfile": "key.txt",
            "certfile": "cert.txt",
            "ca_certs": "ca_certs.txt",
        }

        client = GearmanAdminClient(host_list=[host_config])
        assert len(client.connection_list) == 1

        _assert_gearman_connection_equal(
            conn1=GearmanConnection(host="localhost", port=5000, keyfile="key.txt", certfile="cert.txt", ca_certs="ca_certs.txt"),
            conn2=client.connection_list[0]
        )


class TestGearmanAdminClientCommandHandler:

    command_handler = GearmanAdminClientCommandHandler(
        connection_manager=MockGearmanAdminClient()
    )

    @pytest.mark.parametrize('non_bytes', [1, None, object, u"123"])
    def test_decode_data(self, non_bytes):
        with pytest.raises(TypeError, match="Expecting byte string"):
            self.command_handler.decode_data(non_bytes)

    @pytest.mark.parametrize('non_bytes', [1, None, object, u"123"])
    def test_encode_data(self, non_bytes):
        with pytest.raises(TypeError, match="Expecting byte string"):
            self.command_handler.encode_data(non_bytes)

    def test_decodes_data_correctly(self):
        assert self.command_handler.decode_data(b"123") == b"123"

    def test_encodes_data_correctly(self):
        assert self.command_handler.encode_data(b"123") == b"123"


class BrokenCommandHandler(GearmanAdminClientCommandHandler):
    recv_server_show_jobs = None


class TestBrokenCommandHandlerStateMachine(_StateMachineTest):
    """
    This exists to hit a line that isn't reachable in normal operation.
    """
    command_handler_class = BrokenCommandHandler

    def test_show_jobs_empty(self):
        self.send_server_command(GEARMAN_SERVER_COMMAND_SHOW_JOBS)

        with pytest.raises(ValueError, match="Could not handle command: 'show_jobs'"):
            self.recv_server_response('.')
