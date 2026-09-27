# -*- coding: utf-8 -*-
"""Put `app/` on sys.path for the tests in this directory.

Python already puts the *script's own* directory on sys.path, which was enough
when the tests sat next to the modules. They do not any more, so each test
imports this first. Five lines here beat the same two-liner in three files.
"""
import os
import sys

APP = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   os.pardir, "app"))
if APP not in sys.path:
    sys.path.insert(0, APP)
