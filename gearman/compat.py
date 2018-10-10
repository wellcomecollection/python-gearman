# -*- encoding: utf-8

import sys

PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3


if PY3:
    binary_type = bytes

    def array_to_bytes(arr):
        return arr.tobytes()
else:
    binary_type = str

    def array_to_bytes(arr):
        return arr.tostring()
