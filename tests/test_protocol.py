# -*- encoding: utf-8

import array
import struct

from hypothesis import given
from hypothesis.strategies import binary
import pytest

from gearman import compat, protocol
from gearman.errors import ProtocolError
from tests._core_testing import _GearmanAbstractTest


class TestProtocolBinaryCommands(object):
    #######################
    # Begin parsing tests #
    #######################
    @pytest.mark.parametrize('data,is_response', [
        (b"DDDDAAAABBBBCCCC", True),
        (b"%sAAAABBBBCCCC" % protocol.MAGIC_RES_STRING, False),
        (b"%sAAAABBBBCCCC" % protocol.MAGIC_REQ_STRING, True),
    ])
    def test_parsing_errors_raw(self, data, is_response):
        in_buffer = array.array("b", data)
        with pytest.raises(ProtocolError):
            protocol.parse_binary_command(in_buffer, is_response=is_response)

    @pytest.mark.parametrize('struct_components', [
        # Raise unknown command errors
        (("!4sII", protocol.MAGIC_RES_STRING, 1234, 0)),

        # Raise an error on our imaginary GEARMAN_COMMAND_TEXT_COMMAND
        (("!4sII4s", protocol.MAGIC_RES_STRING, protocol.GEARMAN_COMMAND_TEXT_COMMAND, 4, b'ABCD')),

        # Raise an error on receiving an unexpected payload
        (("!4sII4s", protocol.MAGIC_RES_STRING, protocol.GEARMAN_COMMAND_NOOP, 4, b'ABCD')),

        # Raise an error when receiving some invalid Gearman data
        (("!4sII", protocol.MAGIC_RES_STRING, protocol.GEARMAN_COMMAND_SUBMIT_JOB, 0)),
    ])
    def test_parsing_errors_struct(self, struct_components):
        data = struct.pack(*struct_components)
        in_buffer = array.array("b", data)
        with pytest.raises(ProtocolError):
            protocol.parse_binary_command(in_buffer)

    @given(binary())
    def test_parsing_either_succeeds_or_is_protocolerror(self, in_buffer):
        try:
            protocol.parse_binary_command(array.array("b", in_buffer))
        except ProtocolError:
            pass

    def test_parsing_request(self):
        # Test parsing a request for a job (server side parsing)
        grab_job_command_buffer = struct.pack('!4sII', protocol.MAGIC_REQ_STRING, protocol.GEARMAN_COMMAND_GRAB_JOB_UNIQ, 0)
        grab_job_command_buffer = array.array("b", grab_job_command_buffer)
        cmd_type, cmd_args, cmd_len = protocol.parse_binary_command(grab_job_command_buffer, is_response=False)
        assert cmd_type == protocol.GEARMAN_COMMAND_GRAB_JOB_UNIQ
        assert cmd_args == {}
        assert cmd_len == len(grab_job_command_buffer)

    def test_parsing_without_enough_data(self):
        # Test that we return with nothing to do... received a partial packet
        not_enough_data_command_buffer = struct.pack('!4s', protocol.MAGIC_RES_STRING)
        not_enough_data_command_buffer = array.array("b", not_enough_data_command_buffer)
        cmd_type, cmd_args, cmd_len = protocol.parse_binary_command(not_enough_data_command_buffer)
        assert cmd_type is None
        assert cmd_args is None
        assert cmd_len == 0

        # Test that we return with nothing to do... received a partial packet (expected binary payload of size 4, got 0)
        not_enough_data_command_buffer = struct.pack('!4sII', protocol.MAGIC_RES_STRING, protocol.GEARMAN_COMMAND_ECHO_RES, 4)
        not_enough_data_command_buffer = array.array("b", not_enough_data_command_buffer)
        cmd_type, cmd_args, cmd_len = protocol.parse_binary_command(not_enough_data_command_buffer)
        assert cmd_type is None
        assert cmd_args is None
        assert cmd_len == 0

    def test_parsing_no_args(self):
        noop_command_buffer = struct.pack('!4sII', protocol.MAGIC_RES_STRING, protocol.GEARMAN_COMMAND_NOOP, 0)
        noop_command_buffer = array.array("b", noop_command_buffer)
        cmd_type, cmd_args, cmd_len = protocol.parse_binary_command(noop_command_buffer)
        assert cmd_type == protocol.GEARMAN_COMMAND_NOOP
        assert cmd_args == dict()
        assert cmd_len == len(noop_command_buffer)

    def test_parsing_single_arg(self):
        echoed_string = b'abcd'
        echo_command_buffer = struct.pack('!4sII4s', protocol.MAGIC_RES_STRING, protocol.GEARMAN_COMMAND_ECHO_RES, 4, echoed_string)
        echo_command_buffer = array.array("b", echo_command_buffer)
        cmd_type, cmd_args, cmd_len = protocol.parse_binary_command(echo_command_buffer)
        assert cmd_type == protocol.GEARMAN_COMMAND_ECHO_RES
        assert cmd_args == {u"data": echoed_string}
        assert cmd_len == len(echo_command_buffer)

    def test_parsing_single_arg_with_extra_data(self):
        echoed_string = b'abcd'
        excess_bytes = 5
        excess_data = echoed_string + (protocol.NULL_CHAR * excess_bytes)
        excess_echo_command_buffer = struct.pack('!4sII9s', protocol.MAGIC_RES_STRING, protocol.GEARMAN_COMMAND_ECHO_RES, 4, excess_data)
        excess_echo_command_buffer = array.array("b", excess_echo_command_buffer)

        cmd_type, cmd_args, cmd_len = protocol.parse_binary_command(excess_echo_command_buffer)
        assert cmd_type == protocol.GEARMAN_COMMAND_ECHO_RES
        assert cmd_args == dict(data=echoed_string)
        assert cmd_len == len(excess_echo_command_buffer) - excess_bytes

    def test_parsing_multiple_args(self):
        # Tests ordered argument processing and proper NULL_CHAR splitting
        expected_data = protocol.NULL_CHAR * 4
        binary_payload = protocol.NULL_CHAR.join([b'test', b'function', b'identifier', expected_data])
        payload_size = len(binary_payload)

        uniq_command_buffer = struct.pack('!4sII%ds' % payload_size, protocol.MAGIC_RES_STRING, protocol.GEARMAN_COMMAND_JOB_ASSIGN_UNIQ, payload_size, binary_payload)
        uniq_command_buffer = array.array("b", uniq_command_buffer)
        cmd_type, cmd_args, cmd_len = protocol.parse_binary_command(uniq_command_buffer)
        assert cmd_type == protocol.GEARMAN_COMMAND_JOB_ASSIGN_UNIQ
        assert cmd_args == {
            u"job_handle": b"test",
            u"task": b"function",
            u"unique": b"identifier",
            u"data": expected_data
        }
        assert cmd_len == len(uniq_command_buffer)

    #######################
    # Begin packing tests #
    #######################
    @pytest.mark.parametrize('cmd_type,cmd_args', [
        # Assert we get an unknown command
        (1234, {}),

        # Assert we get a fake command
        (protocol.GEARMAN_COMMAND_TEXT_COMMAND, {}),

        # Assert we get arg mismatch, got 1, expecting 0
        (protocol.GEARMAN_COMMAND_GRAB_JOB, {u"extra": u"arguments"}),

        # Assert we get arg mismatch, got 0, expecting 1
        (protocol.GEARMAN_COMMAND_JOB_CREATED, {}),

        # Assert we get arg mismatch (name), got 1, expecting 1
        (protocol.GEARMAN_COMMAND_JOB_CREATED, {u"extra": "arguments"}),

        # Assert we get a non-string argument
        (protocol.GEARMAN_COMMAND_JOB_CREATED, {u"job_handle": 12345}),

        # Assert we get a non-string argument (expecting BYTES)
        (protocol.GEARMAN_COMMAND_JOB_CREATED, {u"job_handle": u"12345"}),

        # Assert we check for NULLs in all but the "last" argument,
        # where last depends on the cmd_type.
        (protocol.GEARMAN_COMMAND_SUBMIT_JOB,
         {u"task": b"funct\x00ion", u"data": b"abcd", u"unique": b"12345"}),
        (protocol.GEARMAN_COMMAND_SUBMIT_JOB,
         {u"task": b"function", u"data": b"abcd", u"unique": b"123\x00\x0045"}),
    ])
    def test_packing_errors(self, cmd_type, cmd_args):
        with pytest.raises(ProtocolError):
            protocol.pack_binary_command(cmd_type=cmd_type, cmd_args=cmd_args)

    def test_packing_errors_last_arg(self):
        # Assert we check for NULLs in all but the "last" argument,
        # where last depends on the cmd_type.
        protocol.pack_binary_command(
            cmd_type=protocol.GEARMAN_COMMAND_SUBMIT_JOB,
            cmd_args={u"task": b"function", u"data": b"ab\x00cd", u"unique": b"12345"}
        )

    def test_packing_response(self):
        # Test packing a response for a job (server side packing)
        cmd_type = protocol.GEARMAN_COMMAND_NO_JOB
        cmd_args = dict()

        expected_command_buffer = struct.pack('!4sII', protocol.MAGIC_RES_STRING, cmd_type, 0)
        packed_command_buffer = protocol.pack_binary_command(cmd_type, cmd_args, is_response=True)
        assert packed_command_buffer == expected_command_buffer

    def test_packing_no_arg(self):
        cmd_type = protocol.GEARMAN_COMMAND_NOOP
        cmd_args = dict()

        expected_command_buffer = struct.pack('!4sII', protocol.MAGIC_REQ_STRING, cmd_type, 0)
        packed_command_buffer = protocol.pack_binary_command(cmd_type, cmd_args)
        assert packed_command_buffer == expected_command_buffer

    def test_packing_single_arg(self):
        cmd_type = protocol.GEARMAN_COMMAND_ECHO_REQ
        cmd_args = {u"data": b"abcde"}

        expected_payload_size = len(cmd_args['data'])
        expected_format = '!4sII%ds' % expected_payload_size

        expected_command_buffer = struct.pack(
            expected_format,
            protocol.MAGIC_REQ_STRING,
            cmd_type,
            expected_payload_size,
            cmd_args['data']
        )
        packed_command_buffer = protocol.pack_binary_command(cmd_type, cmd_args)
        assert packed_command_buffer == expected_command_buffer

    def test_packing_multiple_args(self):
        cmd_type = protocol.GEARMAN_COMMAND_SUBMIT_JOB
        cmd_args = dict(task=b'function', unique=b'12345', data=b'abcd')

        ordered_parameters = [cmd_args['task'], cmd_args['unique'], cmd_args['data']]

        expected_payload = protocol.NULL_CHAR.join(ordered_parameters)
        expected_payload_size = len(expected_payload)
        expected_format = '!4sII%ds' % expected_payload_size
        expected_command_buffer = struct.pack(expected_format, protocol.MAGIC_REQ_STRING, cmd_type, expected_payload_size, expected_payload)

        packed_command_buffer = protocol.pack_binary_command(cmd_type, cmd_args)
        assert packed_command_buffer == expected_command_buffer


class TestProtocolTextCommands(object):
    #######################
    # Begin parsing tests #
    #######################
    def test_parsing_errors(self):
        received_data = array.array("b", b"Hello\x00there\n")
        with pytest.raises(ProtocolError):
            protocol.parse_text_command(received_data)

    def test_parsing_without_enough_data(self):
        received_data = array.array("b", b"Hello there")
        cmd_type, cmd_response, cmd_len = protocol.parse_text_command(received_data)
        assert cmd_type is None
        assert cmd_response is None
        assert cmd_len == 0

    def test_parsing_single_line(self):
        received_data = array.array("b", b"Hello there\n")
        cmd_type, cmd_response, cmd_len = protocol.parse_text_command(received_data)
        assert cmd_type == protocol.GEARMAN_COMMAND_TEXT_COMMAND
        assert cmd_response == {
            u"raw_text": compat.array_to_bytes(received_data).strip()
        }
        assert cmd_len == len(received_data)

    def test_parsing_multi_line(self):
        sentence_one = array.array("b", b"Hello there\n")
        sentence_two = array.array("b", b"My name is bob\n")
        received_data = sentence_one + sentence_two

        cmd_type, cmd_response, cmd_len = protocol.parse_text_command(received_data)
        assert cmd_type == protocol.GEARMAN_COMMAND_TEXT_COMMAND
        assert cmd_response == {
            u"raw_text": compat.array_to_bytes(sentence_one).strip()
        }
        assert cmd_len == len(sentence_one)

    @pytest.mark.parametrize('cmd_type,cmd_args', [
        # Test bad command type
        (protocol.GEARMAN_COMMAND_NOOP, {}),

        # Test missing args
        (protocol.GEARMAN_COMMAND_TEXT_COMMAND, {}),

        # Test misnamed parameter dict
        (protocol.GEARMAN_COMMAND_TEXT_COMMAND, {u"bad_text": u"abcdefghij"}),
    ])
    def test_packing_errors(self, cmd_type, cmd_args):
        with pytest.raises(ProtocolError):
            protocol.pack_text_command(cmd_type=cmd_type, cmd_args=cmd_args)

    #######################
    # Begin packing tests #
    #######################
    def test_packing_single_line(self):
        expected_string = 'Hello world'
        cmd_type = protocol.GEARMAN_COMMAND_TEXT_COMMAND
        cmd_args = {u"raw_text": expected_string}

        packed_command = protocol.pack_text_command(cmd_type, cmd_args)
        assert packed_command == expected_string


class GearmanCommandHandlerTest(_GearmanAbstractTest):
    """Tests the base CommandHandler class that underpins all other CommandHandlerTests"""
    def _test_recv_command(self):
        # recv_echo_res and recv_error are predefined on the CommandHandler
        self.command_handler.recv_command(protocol.GEARMAN_COMMAND_NOOP)
        self.assert_recv_command(protocol.GEARMAN_COMMAND_NOOP)

        # The mock handler never implemented 'recv_all_yours' so we should get an attribute error here
        with pytest.raises(ValueError):
            self.command_handler.recv_command(protocol.GEARMAN_COMMAND_ALL_YOURS)

    def _test_send_command(self):
        self.command_handler.send_command(protocol.GEARMAN_COMMAND_NOOP)
        self.assert_sent_command(protocol.GEARMAN_COMMAND_NOOP)

        # The mock handler never implemented 'recv_all_yours' so we should get an attribute error here
        self.command_handler.send_command(protocol.GEARMAN_COMMAND_ECHO_REQ, text='hello world')
        self.assert_sent_command(protocol.GEARMAN_COMMAND_ECHO_REQ, text='hello world')

    def assert_recv_command(self, expected_cmd_type, **expected_cmd_args):
        cmd_type, cmd_args = self.command_handler.recv_command_queue.popleft()
        self.assert_commands_equal(cmd_type, expected_cmd_type)
        assert cmd_args == expected_cmd_args

    def assert_sent_command(self, expected_cmd_type, **expected_cmd_args):
        # All commands should be sent via the CommandHandler
        handler_cmd_type, handler_cmd_args = self.command_handler.sent_command_queue.popleft()
        self.assert_commands_equal(handler_cmd_type, expected_cmd_type)
        assert handler_cmd_args == expected_cmd_args

        super(GearmanCommandHandlerTest, self).assert_sent_command(expected_cmd_type, **expected_cmd_args)
