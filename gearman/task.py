import random
from zlib import crc32

class Task(object):
    hooks = ('on_complete', 'on_fail', 'on_retry', 'on_status', 'on_post')

    def __init__(self, func, arg, uniq=None, background=False, high_priority=False,
                 timeout=None, retry_count=0, **kwargs):
        for hook in self.hooks:
            setattr(self, hook, hook in kwargs and [kwargs[hook]] or [])

        self.func          = func
        self.arg           = arg
        self.uniq          = uniq
        self.background    = background
        self.high_priority = high_priority

        self.retries_done = 0
        self.is_finished  = False
        self.handle       = None
        self.result       = None
        self._hash        = crc32(self.func + (self.uniq == '-' and self.arg or self.uniq or str(random.randint(0,999999))))

    def __hash__(self):
        return self._hash

    def merge_hooks(self, task2):
        for hook in self.hooks:
            getattr(self, hook).extend(getattr(task2, hook))

    def complete(self, result):
        self.result = result
        for func in self.on_complete:
            func(result)
        self._finished()

    def fail(self):
        for func in self.on_fail:
            func()
        self._finished()

    def status(self, numerator, denominator):
        for func in self.on_status:
            func(numerator, denominator)

    def retrying(self):
        for func in self.on_retry:
            func()

    def _finished(self):
        self.is_finished = True
        for func in self.on_post:
            func()
        for hook in self.hooks:
            delattr(self, hook) # TODO: perhaps should just clear the lists?

    def __repr__(self):
        return "<Task func='%s'>" % self.func

class Taskset(dict):
    def __init__(self, tasks=[]):
        super(Taskset, self).__init__((hash(t), t) for t in tasks)
        self.handles = {}
        self.cancelled = False

    def add(self, task):
        self[hash(task)] = task

    def add_task(self, *args, **kwargs):
        self.add(Task(*args, **kwargs))

    def cancel(self):
        self.cancelled = True

    def __or__(self, taskset2):
        for k,v in taskset2.iteritems():
            if k in self:
                self[k].merge_hooks(v)
            else:
                self[k] = v # TODO: should clone the task rather than just making a reference
        return self