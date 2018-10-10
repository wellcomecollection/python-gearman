# -*- encoding: utf-8

import collections
import random
import string
import unittest

from gearman import compat
import gearman.util
from gearman.command_handler import GearmanCommandHandler
from gearman.connection import GearmanConnection
from gearman.connection_manager import GearmanConnectionManager, NoopEncoder

from gearman.constants import PRIORITY_NONE, PRIORITY_HIGH, PRIORITY_LOW, DEFAULT_GEARMAN_PORT, JOB_UNKNOWN, JOB_CREATED
from gearman.errors import ConnectionError
from gearman.job import GearmanJob, GearmanJobRequest
from gearman.protocol import get_command_name


def random_bytes():
    s = str(random.random())
    if isinstance(s, compat.binary_type):
        return s
    else:
        return s.encode('ascii')


class MockGearmanConnection(GearmanConnection):
    def __init__(self, host=None, port=DEFAULT_GEARMAN_PORT):
        host = host or '__testing_host__'
        super(MockGearmanConnection, self).__init__(host=host, port=port)

        self._fail_on_bind = False
        self._fail_on_read = False
        self._fail_on_write = False

    def _create_client_socket(self):
        if self._fail_on_bind:
            self.throw_exception(message='mock bind failure')

    def read_data_from_socket(self):
        if self._fail_on_read:
            self.throw_exception(message='mock read failure')

    def send_data_to_socket(self):
        if self._fail_on_write:
            self.throw_exception(message='mock write failure')

    def fileno(self):
        # 73 is the best number, so why not?
        return 73


class MockGearmanConnectionManager(GearmanConnectionManager):
    """Handy mock client base to test Worker/Client/Abstract ClientBases"""
    def poll_connections_once(self, poller, connection_map, timeout=None):
        return set(), set(), set()

    def _register_connections_with_poller(self, connections, poller):
        pass

class _GearmanAbstractTest(unittest.TestCase):
    connection_class = MockGearmanConnection
    connection_manager_class = MockGearmanConnectionManager
    command_handler_class = None

    job_class = GearmanJob

    def setUp(self):
        # Create a new MockGearmanTestClient on the fly
        self.setup_connection_manager()
        self.setup_connection()
        self.setup_command_handler()

    def setup_connection_manager(self):
        testing_attributes = {'command_handler_class': self.command_handler_class, 'connection_class': self.connection_class}
        testing_client_class = type('MockGearmanTestingClient', (self.connection_manager_class, ), testing_attributes)

        self.connection_manager = testing_client_class()

    def setup_connection(self):
        self.connection = self.connection_class()
        self.connection_manager.connection_list = [self.connection]

    def setup_command_handler(self):
        self.connection_manager.establish_connection(self.connection)
        self.command_handler = self.connection_manager.connection_to_handler_map[self.connection]

    def generate_job(self):
        return self.job_class(
            self.connection,
            handle=random_bytes(),
            task=b'__test_ability__',
            unique=random_bytes(),
            data=random_bytes()
        )

    def generate_job_dict(self):
        current_job = self.generate_job()
        return current_job.to_dict()

    def generate_job_request(self, priority=PRIORITY_NONE, background=False):
        job_handle = str(random.random())
        current_job = self.job_class(
            connection=self.connection,
            handle=job_handle,
            task=b'__test_ability__',
            unique=random_bytes(),
            data=random_bytes()
        )
        current_request = GearmanJobRequest(
            current_job,
            initial_priority=priority,
            background=background
        )

        self.assertEqual(current_request.state, JOB_UNKNOWN)

        return current_request

    def assert_jobs_equal(self, job_actual, job_expected):
        # Validates that GearmanJobs are essentially equal
        self.assertEqual(job_actual.handle, job_expected.handle)
        self.assertEqual(job_actual.task, job_expected.task)
        self.assertEqual(job_actual.unique, job_expected.unique)
        self.assertEqual(job_actual.data, job_expected.data)

    def assert_sent_command(self, expected_cmd_type, **expected_cmd_args):
        # Make sure any commands we're passing through the CommandHandler gets properly passed through to the client base
        client_cmd_type, client_cmd_args = self.connection._outgoing_commands.popleft()
        self.assert_commands_equal(client_cmd_type, expected_cmd_type)
        self.assertEqual(client_cmd_args, expected_cmd_args)

    def assert_no_pending_commands(self):
        self.assertEqual(self.connection._outgoing_commands, collections.deque())

    def assert_commands_equal(self, cmd_type_actual, cmd_type_expected):
        self.assertEqual(get_command_name(cmd_type_actual), get_command_name(cmd_type_expected))
