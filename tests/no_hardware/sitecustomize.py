"""Subprocess-only guard, activated by the isolated browser test server."""

import os

if os.environ.get("PYGMALION_TEST_NO_HARDWARE") == "1":
    try:
        import serial
    except ImportError:
        # Poetry's launcher may use a Python without the application dependencies.
        # Its virtualenv child loads this module again before importing the app.
        pass
    else:

        def _forbidden_serial(*args, **kwargs):
            raise AssertionError(
                "Physical serial access is forbidden in this test process"
            )

        serial.Serial = _forbidden_serial
