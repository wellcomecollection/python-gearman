# -*- encoding: utf-8

import collections

import pytest

from gearman.client import GearmanClient
from gearman.client_handler import GearmanClientCommandHandler

from gearman.constants import PRIORITY_NONE, PRIORITY_HIGH, PRIORITY_LOW, JOB_UNKNOWN, JOB_PENDING, JOB_CREATED, JOB_FAILED, JOB_COMPLETE
from gearman.errors import ExceededConnectionAttempts, ServerUnavailable, InvalidClientState
from gearman.protocol import submit_cmd_for_background_priority, GEARMAN_COMMAND_STATUS_RES, GEARMAN_COMMAND_GET_STATUS, GEARMAN_COMMAND_JOB_CREATED, \
    GEARMAN_COMMAND_WORK_STATUS, GEARMAN_COMMAND_WORK_FAIL, GEARMAN_COMMAND_WORK_COMPLETE, GEARMAN_COMMAND_WORK_DATA, GEARMAN_COMMAND_WORK_WARNING

from tests._core_testing import (
    _GearmanAbstractTest,
    MockGearmanConnectionManager,
    MockGearmanConnection,
    random_bytes
)


class MockGearmanClient(GearmanClient, MockGearmanConnectionManager):
    pass


class ClientTest(_GearmanAbstractTest):
    """Test the public client interface"""
    connection_manager_class = MockGearmanClient
    command_handler_class = GearmanClientCommandHandler

    def setUp(self):
        super(ClientTest, self).setUp()
        self.original_handle_connection_activity = self.connection_manager.handle_connection_activity

    def tearDown(self):
        super(ClientTest, self).tearDown()
        self.connection_manager.handle_connection_activity = self.original_handle_connection_activity

    def generate_job_request(self, submitted=True, accepted=True):
        current_request = super(ClientTest, self).generate_job_request()
        if submitted or accepted:
            self.connection_manager.establish_request_connection(current_request)
            self.command_handler.send_job_request(current_request)

        if submitted and accepted:
            self.command_handler.recv_command(GEARMAN_COMMAND_JOB_CREATED, job_handle=current_request.job.handle)
            assert current_request.job.handle in self.command_handler.handle_to_request_map

        return current_request

    def test_establish_request_connection_complex(self):
        # Spin up a bunch of imaginary gearman connections
        failed_connection = MockGearmanConnection()
        failed_connection._fail_on_bind = True

        failed_then_retried_connection = MockGearmanConnection()
        failed_then_retried_connection._fail_on_bind = True

        good_connection = MockGearmanConnection()
        good_connection.connect()

        # Register all our connections
        self.connection_manager.connection_list = [failed_connection, failed_then_retried_connection, good_connection]

        # When we first create our request, our client shouldn't know anything about it
        current_request = self.generate_job_request(submitted=False, accepted=False)
        assert current_request not in self.connection_manager.request_to_rotating_connection_queue

        # Make sure that when we start up, we get our good connection
        chosen_connection = self.connection_manager.establish_request_connection(current_request)
        assert chosen_connection == good_connection

        assert not failed_connection.connected
        assert not failed_then_retried_connection.connected
        assert good_connection.connected

        # No state changed so we should still go to the correct connection
        chosen_connection = self.connection_manager.establish_request_connection(current_request)
        assert chosen_connection == good_connection

        # Pretend like our good connection died so we'll need to choose somethign else
        good_connection._reset_connection()
        good_connection._fail_on_bind = True

        failed_then_retried_connection._fail_on_bind = False
        failed_then_retried_connection.connect()

        # Make sure we rotate good_connection and failed_connection out
        chosen_connection = self.connection_manager.establish_request_connection(current_request)
        assert chosen_connection == failed_then_retried_connection
        assert not failed_connection.connected
        assert failed_then_retried_connection.connected
        assert not good_connection.connected

    def test_establish_request_connection_dead(self):
        self.connection_manager.connection_list = []
        self.connection_manager.command_handlers = {}

        current_request = self.generate_job_request(submitted=False, accepted=False)

        # No connections == death
        with pytest.raises(ServerUnavailable):
            self.connection_manager.establish_request_connection(current_request)

        # Spin up a bunch of imaginary gearman connections
        failed_connection = MockGearmanConnection()
        failed_connection._fail_on_bind = True
        self.connection_manager.connection_list.append(failed_connection)

        # All failed connections == death
        with pytest.raises(ServerUnavailable):
            self.connection_manager.establish_request_connection(current_request)

    def test_auto_retry_behavior(self):
        current_request = self.generate_job_request(submitted=False, accepted=False)

        def fail_then_create_jobs(rx_conns, wr_conns, ex_conns):
            if self.connection_manager.current_failures < self.connection_manager.expected_failures:
                self.connection_manager.current_failures += 1

                # We're going to down this connection and reset state
                assert self.connection.connected
                self.connection_manager.handle_error(self.connection)
                assert not self.connection.connected

                # We're then going to IMMEDIATELY pull this connection back up
                # So we don't bail out of the "self.connection_manager.poll_connections_until_stopped" loop
                self.connection_manager.establish_connection(self.connection)
            else:
                assert current_request.state == JOB_PENDING
                self.command_handler.recv_command(GEARMAN_COMMAND_JOB_CREATED, job_handle=current_request.job.handle)

            return rx_conns, wr_conns, ex_conns

        self.connection_manager.handle_connection_activity = fail_then_create_jobs
        self.connection_manager.expected_failures = 5

        # Now that we've setup our rety behavior, we need to reset the entire state of our experiment
        # First pass should succeed as we JUST touch our max attempts
        self.connection_manager.current_failures = current_request.connection_attempts = 0
        current_request.max_connection_attempts = self.connection_manager.expected_failures + 1
        current_request.state = JOB_UNKNOWN

        self.connection_manager.wait_until_jobs_accepted([current_request])
        assert current_request.state == JOB_CREATED
        assert current_request.connection_attempts == current_request.max_connection_attempts

        # Second pass should fail as we JUST exceed our max attempts
        self.connection_manager.current_failures = current_request.connection_attempts = 0
        current_request.max_connection_attempts = self.connection_manager.expected_failures
        current_request.state = JOB_UNKNOWN

        with pytest.raises(ExceededConnectionAttempts):
            self.connection_manager.wait_until_jobs_accepted([current_request])
        assert current_request.state == JOB_UNKNOWN
        assert current_request.connection_attempts == current_request.max_connection_attempts

    def test_multiple_fg_job_submission(self):
        submitted_job_count = 5
        expected_job_list = [self.generate_job() for _ in range(submitted_job_count)]

        def mark_jobs_created(rx_conns, wr_conns, ex_conns):
            for current_job in expected_job_list:
                self.command_handler.recv_command(GEARMAN_COMMAND_JOB_CREATED, job_handle=current_job.handle)

            return rx_conns, wr_conns, ex_conns

        self.connection_manager.handle_connection_activity = mark_jobs_created

        job_dictionaries = [current_job.to_dict() for current_job in expected_job_list]

        # Test multiple job submission
        job_requests = self.connection_manager.submit_multiple_jobs(job_dictionaries, wait_until_complete=False)
        for current_request, expected_job in zip(job_requests, expected_job_list):
            current_job = current_request.job
            self.assert_jobs_equal(current_job, expected_job)

            assert current_request.priority == PRIORITY_NONE
            assert not current_request.background
            assert current_request.state == JOB_CREATED

            assert not current_request.complete

    def test_single_bg_job_submission(self):
        expected_job = self.generate_job()

        def mark_job_created(rx_conns, wr_conns, ex_conns):
            self.command_handler.recv_command(GEARMAN_COMMAND_JOB_CREATED, job_handle=expected_job.handle)
            return rx_conns, wr_conns, ex_conns

        self.connection_manager.handle_connection_activity = mark_job_created
        job_request = self.connection_manager.submit_job(expected_job.task, expected_job.data, unique=expected_job.unique, background=True, priority=PRIORITY_LOW, wait_until_complete=False)

        current_job = job_request.job
        self.assert_jobs_equal(current_job, expected_job)

        assert job_request.priority == PRIORITY_LOW
        assert job_request.background
        assert job_request.state == JOB_CREATED

        assert job_request.complete

    def test_single_fg_job_submission_timeout(self):
        expected_job = self.generate_job()

        def job_failed_submission(rx_conns, wr_conns, ex_conns):
            return rx_conns, wr_conns, ex_conns

        self.connection_manager.handle_connection_activity = job_failed_submission
        job_request = self.connection_manager.submit_job(expected_job.task, expected_job.data, unique=expected_job.unique, priority=PRIORITY_HIGH, poll_timeout=0.01)

        assert job_request.priority == PRIORITY_HIGH
        assert not job_request.background
        assert job_request.state == JOB_PENDING

        assert not job_request.complete
        assert job_request.timed_out

    def test_single_fg_job_submission_timeout_unspecified_unique(self):
        expected_job = self.generate_job()

        def job_failed_submission(rx_conns, wr_conns, ex_conns):
            return rx_conns, wr_conns, ex_conns

        self.connection_manager.handle_connection_activity = job_failed_submission
        job_request = self.connection_manager.submit_job(
            expected_job.task,
            expected_job.data,
            unique=None,
            priority=PRIORITY_HIGH,
            poll_timeout=0.01
        )

        assert job_request.priority == PRIORITY_HIGH
        assert not job_request.background
        assert job_request.state == JOB_PENDING

        assert not job_request.complete
        assert job_request.timed_out

    def test_wait_for_multiple_jobs_to_complete_or_timeout(self):
        completed_request = self.generate_job_request()
        failed_request = self.generate_job_request()
        timeout_request = self.generate_job_request()

        self.update_requests = True

        def multiple_job_updates(rx_conns, wr_conns, ex_conns):
            # Only give a single status update and have the 3rd job handle timeout
            if self.update_requests:
                self.command_handler.recv_command(GEARMAN_COMMAND_WORK_COMPLETE, job_handle=completed_request.job.handle, data=b'12345')
                self.command_handler.recv_command(GEARMAN_COMMAND_WORK_FAIL, job_handle=failed_request.job.handle)
                self.update_requests = False

            return rx_conns, wr_conns, ex_conns

        self.connection_manager.handle_connection_activity = multiple_job_updates

        finished_requests = self.connection_manager.wait_until_jobs_completed([completed_request, failed_request, timeout_request], poll_timeout=0.01)
        del self.update_requests

        finished_completed_request, finished_failed_request, finished_timeout_request = finished_requests

        self.assert_jobs_equal(finished_completed_request.job, completed_request.job)
        assert finished_completed_request.state == JOB_COMPLETE
        assert finished_completed_request.result == b'12345'
        assert not finished_completed_request.timed_out
        # self.assert_(finished_completed_request.job.handle not in self.command_handler.handle_to_request_map)

        self.assert_jobs_equal(finished_failed_request.job, failed_request.job)
        assert finished_failed_request.state == JOB_FAILED
        assert finished_failed_request.result is None
        assert not finished_failed_request.timed_out
        # self.assert_(finished_failed_request.job.handle not in self.command_handler.handle_to_request_map)

        assert finished_timeout_request.state == JOB_CREATED
        assert finished_timeout_request.result is None
        assert finished_timeout_request.timed_out
        assert finished_timeout_request.job.handle in self.command_handler.handle_to_request_map

    def test_get_job_status(self):
        single_request = self.generate_job_request()

        def retrieve_status(rx_conns, wr_conns, ex_conns):
            self.command_handler.recv_command(GEARMAN_COMMAND_STATUS_RES, job_handle=single_request.job.handle, known='1', running='0', numerator='0', denominator='1')
            return rx_conns, wr_conns, ex_conns

        self.connection_manager.handle_connection_activity = retrieve_status

        job_request = self.connection_manager.get_job_status(single_request)
        request_status = job_request.status
        assert request_status
        assert request_status['known']
        assert not request_status['running']
        assert request_status['numerator'] == 0
        assert request_status['denominator'] == 1
        assert not job_request.timed_out

    def test_get_job_status_unknown(self):
        single_request = self.generate_job_request()
        current_handle = single_request.job.handle
        self.command_handler.recv_command(GEARMAN_COMMAND_WORK_FAIL, job_handle=current_handle)

        def retrieve_status(rx_conns, wr_conns, ex_conns):
            self.command_handler.recv_command(GEARMAN_COMMAND_STATUS_RES, job_handle=current_handle, known='0', running='0', numerator='0', denominator='1')
            return rx_conns, wr_conns, ex_conns

        self.connection_manager.handle_connection_activity = retrieve_status

        job_request = self.connection_manager.get_job_status(single_request)
        request_status = job_request.status
        assert request_status
        assert not request_status['known']
        assert not request_status['running']
        assert request_status['numerator'] == 0
        assert request_status['denominator'] == 1
        assert not job_request.timed_out
        # self.assert_(current_handle not in self.command_handler.handle_to_request_map)

    def test_get_job_status_timeout(self):
        single_request = self.generate_job_request()

        def retrieve_status_timeout(rx_conns, wr_conns, ex_conns):
            return rx_conns, wr_conns, ex_conns

        self.connection_manager.handle_connection_activity = retrieve_status_timeout

        job_request = self.connection_manager.get_job_status(single_request, poll_timeout=0.01)
        assert job_request.timed_out


class ClientCommandHandlerInterfaceTest(_GearmanAbstractTest):
    """Test the public interface a GearmanClient may need to call in order to update state on a GearmanClientCommandHandler"""
    connection_manager_class = MockGearmanClient
    command_handler_class = GearmanClientCommandHandler

    def test_send_job_request(self):
        current_request = self.generate_job_request()
        gearman_job = current_request.job

        for priority in (PRIORITY_NONE, PRIORITY_HIGH, PRIORITY_LOW):
            for background in (False, True):
                current_request.reset()
                current_request.priority = priority
                current_request.background = background

                self.command_handler.send_job_request(current_request)

                queued_request = self.command_handler.requests_awaiting_handles.popleft()
                assert queued_request == current_request

                expected_cmd_type = submit_cmd_for_background_priority(background, priority)
                self.assert_sent_command(expected_cmd_type, task=gearman_job.task, data=gearman_job.data, unique=gearman_job.unique)

    def test_get_status_of_job(self):
        current_request = self.generate_job_request()

        self.command_handler.send_get_status_of_job(current_request)

        self.assert_sent_command(GEARMAN_COMMAND_GET_STATUS, job_handle=current_request.job.handle)


class ClientCommandHandlerStateMachineTest(_GearmanAbstractTest):
    """Test single state transitions within a GearmanWorkerCommandHandler"""
    connection_manager_class = MockGearmanClient
    command_handler_class = GearmanClientCommandHandler

    def generate_job_request(self, submitted=True, accepted=True):
        current_request = super(ClientCommandHandlerStateMachineTest, self).generate_job_request()
        if submitted or accepted:
            self.command_handler.requests_awaiting_handles.append(current_request)
            current_request.state = JOB_PENDING

        if submitted and accepted:
            self.command_handler.recv_command(GEARMAN_COMMAND_JOB_CREATED, job_handle=current_request.job.handle)

        return current_request

    def test_received_job_created(self):
        current_request = self.generate_job_request(accepted=False)

        new_handle = random_bytes()
        self.command_handler.recv_command(GEARMAN_COMMAND_JOB_CREATED, job_handle=new_handle)

        assert current_request.job.handle == new_handle
        assert current_request.state == JOB_CREATED
        assert self.command_handler.handle_to_request_map[new_handle] == current_request

    def test_received_job_created_out_of_order(self):
        assert self.command_handler.requests_awaiting_handles == collections.deque()

        # Make sure we bail cuz we have an empty queue
        with pytest.raises(InvalidClientState):
            self.command_handler.recv_command(
                GEARMAN_COMMAND_JOB_CREATED,
                job_handle=None
            )

    def test_required_state_pending(self):
        current_request = self.generate_job_request(submitted=False, accepted=False)

        new_handle = random_bytes()

        invalid_states = [JOB_UNKNOWN, JOB_CREATED, JOB_COMPLETE, JOB_FAILED]
        for bad_state in invalid_states:
            current_request.state = bad_state

            # We only want to check the state of request... not die if we don't have any pending requests
            self.command_handler.requests_awaiting_handles.append(current_request)

            with pytest.raises(InvalidClientState):
                self.command_handler.recv_command(
                    GEARMAN_COMMAND_JOB_CREATED,
                    job_handle=new_handle
                )

    def test_required_state_queued(self):
        current_request = self.generate_job_request()

        job_handle = current_request.job.handle
        new_data = random_bytes()

        invalid_states = [JOB_UNKNOWN, JOB_PENDING, JOB_COMPLETE, JOB_FAILED]
        for bad_state in invalid_states:
            current_request.state = bad_state

            # All these commands expect to be in JOB_CREATED
            with pytest.raises(InvalidClientState):
                self.command_handler.recv_command(
                    GEARMAN_COMMAND_WORK_DATA,
                    job_handle=job_handle,
                    data=new_data
                )

            with pytest.raises(InvalidClientState):
                self.command_handler.recv_command(
                    GEARMAN_COMMAND_WORK_WARNING,
                    job_handle=job_handle,
                    data=new_data
                )

            with pytest.raises(InvalidClientState):
                self.command_handler.recv_command(
                    GEARMAN_COMMAND_WORK_STATUS,
                    job_handle=job_handle,
                    numerator=0,
                    denominator=1
                )

            with pytest.raises(InvalidClientState):
                self.command_handler.recv_command(
                    GEARMAN_COMMAND_WORK_COMPLETE,
                    job_handle=job_handle,
                    data=new_data
                )

            with pytest.raises(InvalidClientState):
                self.command_handler.recv_command(
                    GEARMAN_COMMAND_WORK_FAIL,
                    job_handle=job_handle
                )

    def test_in_flight_work_updates(self):
        current_request = self.generate_job_request()

        job_handle = current_request.job.handle
        new_data = random_bytes()

        # Test WORK_DATA
        self.command_handler.recv_command(GEARMAN_COMMAND_WORK_DATA, job_handle=job_handle, data=new_data)
        assert current_request.data_updates.popleft() == new_data
        assert current_request.state == JOB_CREATED

        # Test WORK_WARNING
        self.command_handler.recv_command(GEARMAN_COMMAND_WORK_WARNING, job_handle=job_handle, data=new_data)
        assert current_request.warning_updates.popleft() == new_data
        assert current_request.state == JOB_CREATED

        # Test WORK_STATUS
        self.command_handler.recv_command(GEARMAN_COMMAND_WORK_STATUS, job_handle=job_handle, numerator=0, denominator=1)

        assert current_request.state == JOB_CREATED

    def test_work_complete(self):
        current_request = self.generate_job_request()

        job_handle = current_request.job.handle
        new_data = random_bytes()
        self.command_handler.recv_command(GEARMAN_COMMAND_WORK_COMPLETE, job_handle=job_handle, data=new_data)

        assert current_request.result == new_data
        assert current_request.state == JOB_COMPLETE

    def test_work_fail(self):
        current_request = self.generate_job_request()

        job_handle = current_request.job.handle
        self.command_handler.recv_command(GEARMAN_COMMAND_WORK_FAIL, job_handle=job_handle)

        assert current_request.state == JOB_FAILED

    def test_status_request(self):
        current_request = self.generate_job_request()

        job_handle = current_request.job.handle

        assert current_request.status == {}

        self.command_handler.recv_command(GEARMAN_COMMAND_STATUS_RES, job_handle=job_handle, known='1', running='1', numerator='0', denominator='1')

        assert current_request.status['handle'] == job_handle
        assert current_request.status['known']
        assert current_request.status['running']
        assert current_request.status['numerator'] == 0
        assert current_request.status['denominator'] == 1
