"""תשתית בדיקות: מסד נתונים זמני לכל מקרה בדיקה."""

import os
import tempfile
import unittest

from pronear import config, db


class DBTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        config.DB_PATH = os.path.join(self._dir.name, "test.db")
        db.close_conn()
        db.init_db()

    def tearDown(self):
        db.close_conn()
        self._dir.cleanup()
