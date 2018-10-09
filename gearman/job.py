# -*- encoding: utf-8

import collections
from gearman.constants import PRIORITY_NONE, JOB_UNKNOWN, JOB_CREATED, JOB_FAILED, JOB_COMPLETE


class GearmanJob(object):
    """Represents the basics of a job... used in GearmanClient / GearmanWorker to represent job states"""
    def __init__(self, connection, handle, task, unique, data):
        self.connection = connection
        self.handle = handle

        self.task = task
        self.unique = unique
        self.data = data

    def __repr__(self):
        return '%s(connection=%r, handle=%r, task=%r, unique=%r, data=%r)' % (
            type(self).__name__,
            self.connection,
            self.handle,
            self.task,
            self.unique,
            self.data
        )

    def to_dict(self):
        return dict(task=self.task, job_handle=self.handle, unique=self.unique, data=self.data)


class GearmanJobRequest(object):
    """Represents a job request... used in GearmanClient to represent job states"""
    def __init__(self, gearman_job, initial_priority=PRIORITY_NONE, background=False, max_attempts=1):
        self.gearman_job = gearman_job

        self.priority = initial_priority
        self.background = background

        self.connection_attempts = 0
        self.max_connection_attempts = max_attempts

        self.initialize_request()

    def __repr__(self):
        return '%s(gearman_job=%r, initial_priority=%r, background=%r, max_attempts=%r)' % (
            type(self).__name__,
            self.gearman_job,
            self.priority,
            self.background,
            self.max_connection_attempts
        )

    def initialize_request(self):
        # Holds WORK_COMPLETE responses
        self.result = None

        # Holds WORK_EXCEPTION responses
        self.exception = None

        # Queues to hold WORK_WARNING, WORK_DATA responses
        self.warning_updates = collections.deque()
        self.data_updates = collections.deque()

        # Holds WORK_STATUS / STATUS_REQ responses
        self.status = {}

        self.state = JOB_UNKNOWN
        self.timed_out = False

    def reset(self):
        self.initialize_request()
        self.connection = None
        self.handle = None

    @property
    def job(self):
        return self.gearman_job

    @property
    def complete(self):
        background_complete = bool(self.background and self.state in (JOB_CREATED))
        foreground_complete = bool(not self.background and self.state in (JOB_FAILED, JOB_COMPLETE))

        actually_complete = background_complete or foreground_complete
        return actually_complete
