import os
import ramcloud
import time
import datetime
import Table_pb2
import unittest
from pyexpect import expect
from timeout_decorator import timeout
from cluster_utils import ten_minutes
import cluster_utils as cu

x = cu.ClusterClient()

# exercise our RAMCloud cluster with some bursts of read and write activity
class TestReadWrite(unittest.TestCase):
    def setUp(self):
        x.setUp(num_nodes = 4)
        x.createTestValue()

    def tearDown(self):
        x.outputLogs()
        x.tearDown()

    # 15 minute timeout
    @unittest.skip("need to investigate why 15 minutes is sometimes not enough")
    @timeout(900)
    def test_do_reads_and_writes(self):
        value = x.rc_client.read(x.table, 'testKey')
        expect(value).equals(('testValue', 1))
        for j in range(0, 4):
            ts1 = time.time()
            for i in range(0, 4096):
                x.rc_client.write(x.table, 'testKey_%d_FOOBARBAZDEADBEEF%d' % (j, i), 'testValue_%d_FOOBARBAZDEADBEEF%d' % (j, i))
            for i in range(0, 4096):
                value = x.rc_client.read(x.table, 'testKey_%d_FOOBARBAZDEADBEEF%d' % (j, i))
                expect(value).equals(('testValue_%d_FOOBARBAZDEADBEEF%d' % (j, i), (4096*j)+i+2))
            ts2 = time.time()
            print("That one took:", datetime.datetime.fromtimestamp(ts2-ts1).strftime('%H:%M:%S:%f'))

if __name__ == '__main__':
    unittest.main()
