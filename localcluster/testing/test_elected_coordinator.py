import os
import ramcloud
import time
import Table_pb2
import unittest
from pyexpect import expect
from timeout_decorator import timeout
from cluster_utils import ten_minutes
import cluster_utils as cu

x = cu.ClusterClient()

class TestElectedCoordinator(unittest.TestCase):
    def setUp(self):
        x.setUp(num_nodes = 4)
        x.createTestValue()

    def tearDown(self):
        x.tearDown()

    @timeout(ten_minutes)
    def test_down_can_still_read(self):
        value = x.rc_client.read(x.table, 'testKey')
        expect(value).equals(('testValue', 1))

        # find the host corresponding to the elected coordinator, kill its rc-coordinator!
        # we should still be able to get the testKey.
        zk_client = cu.get_zookeeper_client(x.ensemble)
        locator =  zk_client.get('/ramcloud/main/coordinator')[0].decode()
        host = cu.get_host(locator)
        x.node_containers[host].exec_run('pkill -SIGKILL rc-coordinator')

        # after the coordinator is down, we try to read. We expect
        # to see our value.
        value = x.rc_client.read(x.table, 'testKey')
        time.sleep(6)  # time needed for a new coordinator to be elected & results to show in zk
        new_locator =  zk_client.get('/ramcloud/main/coordinator')[0].decode()

        expect(value).equals(('testValue', 1))
        expect(new_locator).not_equals(None)
        expect(new_locator).not_equals(locator)

if __name__ == '__main__':
    unittest.main()
