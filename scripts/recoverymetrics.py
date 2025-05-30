#!/usr/bin/env python3

# Copyright (c) 2011 Stanford University
#
# Permission to use, copy, modify, and distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR(S) DISCLAIM ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL AUTHORS BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

"""
This program scans the log files generated by a RAMCloud recovery,
extracts performance metrics, and print a summary of interesting data
from those metrics.
"""


from glob import glob
from optparse import OptionParser
from pprint import pprint
from functools import partial
import math
import os
import random
import re
import sys

from common import *

__all__ = ['parseRecovery', 'makeReport']

### Utilities:

class AttrDict(dict):
    """A mapping with string keys that aliases x.y syntax to x['y'] syntax.

    The attribute syntax is easier to read and type than the item syntax.
    """
    def __getattr__(self, name):
        if name not in self:
            self[name] = AttrDict()
        return self[name]
    def __setattr__(self, name, value):
        self[name] = value
    def __delattr__(self, name):
        del self[name]

    def assign(self, path, value):
        """
        Given a hierarchical path such as 'x.y.z' and
        a value, perform an assignment as if the statement
        self.x.y.z had been invoked.
        """
        names = path.split('.')
        container = self
        for name in names[0:-1]:
            if name not in container:
                container[name] = AttrDict()
            container = container[name]
        container[names[-1]] = value

def parse(f):
    """
    Scan a log file containing metrics for several servers, and return
    a list of AttrDicts, one containing the metrics for each server.
    """

    list = []
    for line in f:
        match = re.match('.* Metrics: (.*)$', line)
        if not match:
            continue
        info = match.group(1)
        start = re.match('begin server (.*)', info)
        if start:
            list.append(AttrDict())
            # Compute a human-readable name for this server (ideally
            # just its short host name).
            short_name = re.search('host=([^,]*)', start.group(1))
            if short_name:
               list[-1].server = short_name.group(1)
            else:
               list[-1].server = start.group(1)
            continue;
        if len(list) == 0:
            raise Exception('metrics data before "begin server" in %s'
                              % f.name)
        var, value = info.split(' ')
        list[-1].assign(var, int(value))
    if len(list) == 0:
        raise Exception('no metrics in %s' % f.name)
    return list

def maxTuple(tuples):
    """Return the tuple whose first element is largest."""
    maxTuple = None;
    maxValue = 0.0;
    for tuple in tuples:
        if tuple[0] > maxValue:
            maxValue = tuple[0]
            maxTuple = tuple
    return maxTuple

def minTuple(tuples):
    """Return the tuple whose first element is smallest."""
    minTuple = None;
    minValue = 1e100;
    for tuple in tuples:
        if tuple[0] < minValue:
            minValue = tuple[0]
            minTuple = tuple
    return minTuple

def values(s):
    """Return a sequence of the second items from a sequence."""
    return [p[1] for p in s]

def scale(points, scalar):
    """Try really hard to scale 'points' by 'scalar'.

    @type  points: mixed
    @param points: Points can either be:

        - a sequence of pairs, in which case the second item will be scaled,
        - a list, or
        - a number

    @type  scalar: number
    @param scalar: the amount to multiply points by
    """

    if type(points) is list:
        try:
            return [(k, p * scalar) for k, p in points]
        except TypeError:
            return [p * scalar for p in points]
    else:
        return points * scalar

def toString(x):
    """Return a reasonable string conversion for the argument."""
    if type(x) is int:
        return '{0:7d}'.format(x)
    elif type(x) is float:
        return '{0:7.2f}'.format(x)
    else:
        return '{0:>7s}'.format(x)

### Summary functions
# This is a group of functions that can be passed in to Section.line() to
# affect how the line is summarized.
# Each one takes the following arguments:
#  - values, which is a list of numbers
#  - unit, which is a short string specifying the units for values
# Each returns a list, possibly empty, of strings to contribute to the summary
# text. The summary strings are later displayed with a delimiter or line break
# in between.

def AVG(values, unit):
    """Returns the average of its values."""
    if max(values) > min(values):
        r = toString(sum(values) / len(values))
        if unit:
            r += ' ' + unit
        r += ' avg'
    else:
        r = toString(values[0])
        if unit:
            r += ' ' + unit
    return [r]

def MIN(values, unit):
    """Returns the minimum of the values if the range is non-zero."""
    if len(values) < 2 or max(values) == min(values):
        return []
    r = toString(min(values))
    if unit:
        r += ' ' + unit
    r += ' min'
    return [r]

def MAX(values, unit):
    """Returns the maximum of the values if the range is non-zero."""
    if len(values) < 2 or max(values) == min(values):
        return []
    r = toString(max(values))
    if unit:
        r += ' ' + unit
    r += ' max'
    return [r]

def SUM(values, unit):
    """Returns the sum of the values if there are any."""
    if len(values) == 0:
        return []
    r = toString(sum(values))
    if unit:
        r += ' ' + unit
    r += ' total'
    return [r]

def FRAC(total):
    """Returns a function that shows the average percentage of the values from
    the total given."""
    def realFrac(values, unit):
        r = toString(sum(values) / len(values) / total * 100)
        r += '%'
        if max(values) > min(values):
            r += ' avg'
        return [r]
    return realFrac

def CUSTOM(s):
    """Returns a function that returns the string or list of strings given.

    This is useful when you need custom processing that doesn't fit in any of
    the other summary functions and is too specific to merit a new summary
    function.
    """
    def realCustom(values, unit):
        if type(s) is list:
            return s
        else:
            return [s]
    return realCustom


### Report structure:

class Report(object):
    """This produces a report which can be uploaded to dumpstr.

    It is essentially a list of Sections.
    """

    def __init__(self):
        self.sections = []

    def add(self, section):
        """Add a new Section to the report."""
        self.sections.append(section)
        return section

    def jsonable(self):
        """Return a representation of the report that can be JSON-encoded in
        dumpstr format.
        """

        doc = [section.jsonable() for section in self.sections if section]
        return doc

class Section(object):
    """A part of a Report consisting of lines with present metrics."""

    def __init__(self, key):
        """
        @type  key: string
        @param key: a stable, unique string identifying the section

            This should not ever be changed, as dumpstr's labels and
            descriptions are looked up by this key.
        """

        self.key = key
        self.lines = []

    def __len__(self):
        return len(self.lines)

    def jsonable(self):
        """Return a representation of the section that can be JSON-encoded in
        dumpstr format.
        """
        return {'key': self.key, 'lines': self.lines}

    def line(self, key, points, unit='',
             summaryFns=[AVG, MAX]):
        """Add a line to the Section.

        @type  key: string
        @param key: a stable, unique string identifying the line

            This should not ever be changed, as dumpstr's labels and
            descriptions are looked up by this key.

        @type  points: number, string, list of numbers, or
                       list of pairs of (string label, number)
        @param points: the data, in detail

        @type  unit: string
        @param unit: a short string specifying the units for values

        @type  summaryFn: list of summary functions
        @param summaryFn: used to create a short summary of the data

            See the big comment block under "Summary functions" above.
        """

        if unit:
            spaceUnit = ' ' + unit
        else:
            spaceUnit = ''

        if type(points) is str:
            summary = points
        else:
            values = []
            if type(points) is list:
                for point in points:
                    try:
                        label, point = point
                    except TypeError:
                        pass
                    assert type(point) in [int, float]
                    values.append(point)
            else:
                assert type(points) in [int, float]
                values.append(points)

            summary = []
            for fn in summaryFns:
                summary += fn(values, unit)

        self.lines.append({'key': key,
                           'summary': summary,
                           'points': points,
                           'unit': unit})

    def ms(self, key, points, total=None):
        """A commonly used line type for printing in milliseconds.

        @param key: see line

        @param ponts: The points given in units of seconds (they will be
        scaled by 1000 internally).

        @param total: If the time is a fraction of some total, this is that
                      total, in seconds.

        """
        summaryFns = [AVG, MAX]
        if total:
            summaryFns.append(FRAC(total * 1000))
        self.line(key, scale(points, 1000), unit='ms', summaryFns=summaryFns)

def parseRecovery(recovery_dir):
    data = AttrDict()
    data.log_dir = os.path.realpath(os.path.expanduser(recovery_dir))
    logFile = glob('%s/client*.*.log' % recovery_dir)[0]

    data.backups = []
    data.masters = []
    data.servers = parse(open(logFile))
    for server in data.servers:
        # Each iteration of this loop corresponds to one server's
        # log file. Figure out whether this server is a coordinator,
        # master, backup, or both master and backup, and put the
        # data in appropriate sub-lists.
        if server.backup.recoveryCount > 0:
            data.backups.append(server)
        if server.master.recoveryCount > 0:
            data.masters.append(server)
        if server.coordinator.recoveryCount > 0:
            data.coordinator = server

    # Calculator the total number of unique server nodes (subtract 1 for the
    # coordinator).
    data.totalNodes = len(set([server.server for server in data.servers])) - 1
        
    data.client = AttrDict()
    for line in open(glob('%s/client*.*.log' % recovery_dir)[0]):
        m = re.search(
            r'\bRecovery completed in (\d+) ns, failure detected in (\d+) ns\b',
            line)
        if m:
            failureDetectionNs = int(m.group(2))
            data.client.recoveryNs = int(m.group(1)) - failureDetectionNs
            data.client.failureDetectionNs = failureDetectionNs
    return data

def rawSample(data):
    """Prints out some raw data for debugging"""

    print('Client:')
    pprint(data.client)
    print('Coordinator:')
    pprint(data.coordinator)
    print()
    print('Sample Master:')
    pprint(random.choice(data.masters))
    print()
    print('Sample Backup:')
    pprint(random.choice(data.backups))

def rawFull(data):
    """Prints out all raw data for debugging"""

    pprint(data)

def makeReport(data):
    """Generate ASCII report"""

    coord = data.coordinator
    masters = data.masters
    backups = data.backups
    servers = data.servers

    recoveryTime = data.client.recoveryNs / 1e9
    failureDetectionTime = data.client.failureDetectionNs / 1e9
    report = Report()

    # TODO(ongaro): Size distributions of filtered segments

    def make_fail_fun(fun, fail):
        """Wrap fun to return fail instead of throwing ZeroDivisionError."""
        def fun2(x):
            try:
                return fun(x)
            except ZeroDivisionError:
                return fail
        return fun2

    def on_masters(fun, fail=0):
        """Call a function on each master,
        replacing ZeroDivisionErrors with 'fail'."""
        fun2 = make_fail_fun(fun, fail)
        return [(master.serverId, fun2(master)) for master in masters]

    def on_backups(fun, fail=0):
        """Call a function on each backup,
        replacing ZeroDivisionErrors with 'fail'."""
        fun2 = make_fail_fun(fun, fail)
        return [(backup.serverId, fun2(backup)) for backup in backups]


    summary = report.add(Section('Summary'))
    summary.line('Recovery time', recoveryTime, 's')
    summary.line('Failure detection time', failureDetectionTime, 's')
    summary.line('Recovery + detection time',
                 recoveryTime + failureDetectionTime, 's')
    summary.line('Masters', len(masters))
    summary.line('Backups', len(backups))
    summary.line('Total nodes', data.totalNodes)
    summary.line('Replicas',
                 masters[0].master.replicas)
    summary.line('Objects per master',
                 on_masters(lambda m: m.master.liveObjectCount))
    summary.line('Object size',
                 on_masters(lambda m: m.master.liveObjectBytes /
                                      m.master.liveObjectCount),
                 'bytes')

    summary.line('Total recovery segment entries',
                 sum([master.master.recoverySegmentEntryCount
                      for master in masters]))

    summary.line('Total live object space',
                 sum([master.master.liveObjectBytes
                      for master in masters]) / 1024.0 / 1024.0,
                 'MB')

    summary.line('Total recovery segment space w/ overhead',
                 sum([master.master.segmentReadByteCount
                      for master in masters]) / 1024.0 / 1024.0,
                 'MB')

    if backups:
        storageTypes = set([backup.backup.storageType for backup in backups])
        if len(storageTypes) > 1:
            storageTypeStr = 'mixed'
        else:
            storageType = storageTypes.pop()
            if storageType == 1:
                storageTypeStr = 'memory'
            elif storageType == 2:
                storageTypeStr = 'disk'
            else:
                storageTypeStr = 'unknown (%s)' % storageType
        summary.line('Storage type', storageTypeStr)
    summary.line('Log directory', data.log_dir)

    coordSection = report.add(Section('Coordinator Time'))
    coordSection.ms('Total',
                    coord.coordinator.recoveryTicks /
                    coord.clockFrequency,
                    total=recoveryTime)

    coordSection.ms('Starting recovery on backups',
        coord.coordinator.recoveryBuildReplicaMapTicks / coord.clockFrequency,
        total=recoveryTime)
    coordSection.ms('Starting recovery on masters',
        coord.coordinator.recoveryStartTicks / coord.clockFrequency,
        total=recoveryTime)
    coordSection.ms('Tablets recovered',
        coord.rpc.recovery_master_finishedTicks / coord.clockFrequency,
        total=recoveryTime)
    coordSection.ms('Completing recovery on backups',
        coord.coordinator.recoveryCompleteTicks / coord.clockFrequency,
        total=recoveryTime)
    coordSection.ms('Get table config',
        coord.rpc.get_table_configTicks / coord.clockFrequency,
        total=recoveryTime)
    coordSection.ms('Other',
        ((coord.coordinator.recoveryTicks -
          coord.coordinator.recoveryBuildReplicaMapTicks -
          coord.coordinator.recoveryStartTicks -
          coord.rpc.get_table_configTicks -
          coord.rpc.recovery_master_finishedTicks) /
         coord.clockFrequency),
        total=recoveryTime)
    coordSection.ms('Receiving in transport',
        coord.transport.receive.ticks / coord.clockFrequency,
        total=recoveryTime)

    masterSection = report.add(Section('Recovery Master Time'))

    recoveryMasterTime = sum([m.master.recoveryTicks / m.clockFrequency for m in masters]) / len(masters)
    def master_ticks(label, field):
        """This is a shortcut for adding to the masterSection a recorded number
        of ticks that are a fraction of the total recovery.

        @type  label: string
        @param label: the key for the line

        @type  field: string
        @param field: the field within a master's metrics that collected ticks
        """
        masterSection.ms(label,
                         on_masters(lambda m: eval('m.' + field) /
                                              m.clockFrequency),
                         total=recoveryMasterTime)

    masterSection.ms('Total (versus end-to-end recovery time)',
                     on_masters(lambda m: m.master.recoveryTicks /
                                          m.clockFrequency),
                     total=recoveryTime)
    master_ticks('Total',
                 'master.recoveryTicks')
    master_ticks('Waiting for incoming segments',
                 'master.segmentReadStallTicks')
    master_ticks('Inside recoverSegment',
                 'master.recoverSegmentTicks')
    master_ticks('Final log sync time',
                 'master.logSyncTicks')
    master_ticks('Removing tombstones',
                 'master.removeTombstoneTicks')
    masterSection.ms('Other',
                     on_masters(lambda m: (m.master.recoveryTicks -
                                           m.master.segmentReadStallTicks -
                                           m.master.recoverSegmentTicks -
                                           m.master.logSyncTicks -
                                           m.master.removeTombstoneTicks) /
                                          m.clockFrequency),
                     total=recoveryTime)

    recoverSegmentTime = sum([m.master.recoverSegmentTicks / m.clockFrequency  for m in masters]) / len(masters)
    recoverSegmentSection = report.add(Section('Recovery Master recoverSegment Time'))
    def recoverSegment_ticks(label, field):
        recoverSegmentSection.ms(label,
                         on_masters(lambda m: eval('m.' + field) /
                                              m.clockFrequency),
                         total=recoverSegmentTime)
    recoverSegmentSection.ms('Total (versus end-to-end recovery time)',
                     on_masters(lambda m: m.master.recoverSegmentTicks /
                                          m.clockFrequency),
                     total=recoveryTime)
    recoverSegment_ticks('Total',
                 'master.recoverSegmentTicks')
    recoverSegment_ticks('Managing replication',
                 'master.backupInRecoverTicks')
    recoverSegment_ticks('Verify checksum',
                 'master.verifyChecksumTicks')
    recoverSegment_ticks('Segment append',
                 'master.segmentAppendTicks')
    # No longer measured: could be useful in the future. Make sure to add it to Other if used again.
    # recoverSegment_ticks('Segment append copy',
    #              'master.segmentAppendCopyTicks')
    recoverSegmentSection.ms('Other',
                     on_masters(lambda m: (m.master.recoverSegmentTicks -
                                           m.master.backupInRecoverTicks -
                                           m.master.verifyChecksumTicks -
                                           m.master.segmentAppendTicks) /
                                          m.clockFrequency),
                     total=recoverSegmentTime)

    replicaManagerTime = sum([m.master.backupInRecoverTicks / m.clockFrequency  for m in masters]) / len(masters)
    replicaManagerSection = report.add(Section('Recovery Master ReplicaManager Time during recoverSegment'))
    def replicaManager_ticks(label, field):
        replicaManagerSection.ms(label,
                         on_masters(lambda m: eval('m.' + field) /
                                              m.clockFrequency),
                         total=replicaManagerTime)
    replicaManagerSection.ms('Total (versus end-to-end recovery time)',
                     on_masters(lambda m: m.master.backupInRecoverTicks /
                                          m.clockFrequency),
                     total=recoveryTime)
    replicaManager_ticks('Total',
                 'master.backupInRecoverTicks')
    replicaManagerSection.ms('Posting write RPCs for TX to transport',
                     on_masters(lambda m: (m.master.recoverSegmentPostingWriteRpcTicks) /
                                          m.clockFrequency),
                     total=replicaManagerTime)
    replicaManagerSection.ms('Other',
                     on_masters(lambda m: (m.master.backupInRecoverTicks -
                                           m.master.recoverSegmentPostingWriteRpcTicks) /
                                          m.clockFrequency),
                     total=replicaManagerTime)

    masterStatsSection = report.add(Section('Recovery Master Stats'))
    def masterStats_ticks(label, field):
        masterStatsSection.ms(label,
                         on_masters(lambda m: eval('m.' + field) /
                                              m.clockFrequency),
                         total=recoveryTime)
    masterStatsSection.line('Final log sync amount',
        on_masters(lambda m: (m.master.logSyncBytes / 2**20)),
        unit='MB',
        summaryFns=[AVG, MIN, SUM])
    masterStatsSection.line('Total replication amount',
        on_masters(lambda m: (m.master.replicationBytes / 2**20)),
        unit='MB',
        summaryFns=[AVG, MIN, SUM])
    masterStatsSection.line('Total replication during replay',
        on_masters(lambda m: ((m.master.replicationBytes - m.master.logSyncBytes) / 2**20)),
        unit='MB',
        summaryFns=[AVG, MIN, SUM])

    masterStats_ticks('Opening sessions',
                 'transport.sessionOpenTicks')
    masterStats_ticks('Receiving in transport',
                 'transport.receive.ticks')
    masterStats_ticks('Transmitting in transport',
                 'transport.transmit.ticks')

    masterStats_ticks('Client RPCs Active',
                 'transport.clientRpcsActiveTicks')
    masterStatsSection.ms('Average GRD completion time',
        on_masters(lambda m: (m.master.segmentReadTicks /
                              m.master.segmentReadCount /
                              m.clockFrequency)))

    # There used to be a bunch of code here for analyzing the variance in
    # session open times. We don't open sessions during recovery anymore, so
    # I've deleted this code. Look in the git repo for mid-2011 if you want it
    # back. -Diego

    masterStatsSection.line('Log replication rate',
        on_masters(lambda m: (m.master.replicationBytes / m.master.replicas / 2**20 /
                              (m.master.replicationTicks / m.clockFrequency))),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])
    masterStatsSection.line('Log replication rate during replay',
        on_masters(lambda m: ((m.master.replicationBytes - m.master.logSyncBytes)
                               / m.master.replicas / 2**20 /
                              ((m.master.replicationTicks - m.master.logSyncTicks)/ m.clockFrequency))),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])
    masterStatsSection.line('Log replication rate during log sync',
        on_masters(lambda m: (m.master.logSyncBytes / m.master.replicas / 2**20 /
                              (m.master.logSyncTicks / m.clockFrequency))),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])

    masterStats_ticks('Replication',
                 'master.replicationTicks')

    masterStatsSection.ms('TX active',
        on_masters(lambda m: (m.transport.infiniband.transmitActiveTicks /
                              m.clockFrequency)),
        total=recoveryTime)

    replicationTime = sum([m.master.replicationTicks / m.clockFrequency for m in masters]) / float(len(masters))
    logSyncTime = sum([m.master.logSyncTicks / m.clockFrequency for m in masters]) / float(len(masters))
    replayTime = sum([(m.master.replicationTicks - m.master.logSyncTicks)/ m.clockFrequency for m in masters]) / float(len(masters))

    masterStatsSection.ms('TX active during replication',
        on_masters(lambda m: (m.master.replicationTransmitActiveTicks /
                              m.clockFrequency)),
        total=replicationTime)
    masterStatsSection.ms('TX active during replay',
        on_masters(lambda m: ((m.master.replicationTransmitActiveTicks - m.master.logSyncTransmitActiveTicks) /
                              m.clockFrequency)),
        total=replayTime)
    masterStatsSection.ms('TX active during log sync',
        on_masters(lambda m: (m.master.logSyncTransmitActiveTicks /
                              m.clockFrequency)),
        total=logSyncTime)

    masterStatsSection.line('TX active rate during replication',
        on_masters(lambda m: m.master.replicationBytes / 2**20 / (m.master.replicationTransmitActiveTicks /
                              m.clockFrequency)),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])
    masterStatsSection.line('TX active rate during replay',
        on_masters(lambda m: (m.master.replicationBytes - m.master.logSyncBytes) / 2**20 / ((m.master.replicationTransmitActiveTicks - m.master.logSyncTransmitActiveTicks) /
                              m.clockFrequency)),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])
    masterStatsSection.line('TX active rate during log sync',
        on_masters(lambda m: m.master.logSyncBytes / 2**20 / (m.master.logSyncTransmitActiveTicks /
                              m.clockFrequency)),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])

    masterStats_ticks('Copying for TX during replication',
                 'master.replicationTransmitCopyTicks')
    masterStatsSection.ms('Copying for TX during replay',
        on_masters(lambda m: (m.master.replicationTransmitCopyTicks -
                              m.master.logSyncTransmitCopyTicks) / m.clockFrequency),
        total=recoveryTime)
    masterStats_ticks('Copying for TX during log sync',
                 'master.logSyncTransmitCopyTicks')
    masterStatsSection.line('Copying for tx during replication rate',
        on_masters(lambda m: (m.master.replicationBytes / m.master.replicas / 2**20 /
                              (m.master.replicationTransmitCopyTicks / m.clockFrequency))),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])
    masterStatsSection.line('Copying for TX during replay rate',
        on_masters(lambda m: ((m.master.replicationBytes - m.master.logSyncBytes) / m.master.replicas / 2**20 /
                              ((m.master.replicationTransmitCopyTicks - m.master.logSyncTransmitCopyTicks) / m.clockFrequency))),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])
    masterStatsSection.line('Copying for TX during log sync rate',
        on_masters(lambda m: (m.master.logSyncBytes / m.master.replicas / 2**20 /
                              (m.master.logSyncTransmitCopyTicks / m.clockFrequency))),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])

    masterStatsSection.line('Max active replication tasks',
        on_masters(lambda m: m.master.replicationTasks),
        unit='tasks',
        summaryFns=[AVG, MIN, SUM])

    masterStatsSection.line('Memory read bandwidth used during replay',
        on_masters(lambda m: (m.master.replayMemoryReadBytes / 2**20 /
                              ((m.master.recoveryTicks - m.master.logSyncTicks) / m.clockFrequency))),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])
    masterStatsSection.line('Memory write bandwidth used during replay',
        on_masters(lambda m: (m.master.replayMemoryWrittenBytes / 2**20 /
                              ((m.master.recoveryTicks - m.master.logSyncTicks) / m.clockFrequency))),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])

    backupSection = report.add(Section('Backup Time'))

    def backup_ticks(label, field):
        """This is a shortcut for adding to the backupSection a recorded number
        of ticks that are a fraction of the total recovery.

        @type  label: string
        @param label: the key for the line

        @type  field: string
        @param field: the field within a backup's metrics that collected ticks
        """
        backupSection.ms(label,
                         on_backups(lambda b: eval('b.' + field) /
                                              b.clockFrequency),
                         total=recoveryTime)

    backup_ticks('RPC service time',
                 'backup.serviceTicks')
    backup_ticks('startReadingData RPC',
                 'rpc.backup_startreadingdataTicks')
    backup_ticks('write RPC',
                 'rpc.backup_writeTicks')
    backup_ticks('Write copy',
                 'backup.writeCopyTicks')
    backupSection.ms('Other write RPC',
        on_backups(lambda b: (b.rpc.backup_writeTicks -
                              b.backup.writeCopyTicks) /
                             b.clockFrequency),
        total=recoveryTime)
    backup_ticks('getRecoveryData RPC',
                 'rpc.backup_getrecoverydataTicks')
    backupSection.ms('Other',
        on_backups(lambda b: (b.backup.serviceTicks -
                              b.rpc.backup_startreadingdataTicks -
                              b.rpc.backup_writeTicks -
                              b.rpc.backup_getrecoverydataTicks) /
                             b.clockFrequency),
        total=recoveryTime)
    backup_ticks('Transmitting in transport',
                 'transport.transmit.ticks')
    backup_ticks('Filtering segments',
                 'backup.filterTicks')
    backup_ticks('Reading+filtering replicas',
                 'backup.readingDataTicks')
    backup_ticks('Reading replicas from disk',
                 'backup.storageReadTicks')
    backupSection.line('getRecoveryData completions',
        on_backups(lambda b: b.backup.readCompletionCount))
    backupSection.line('getRecoveryData retry fraction',
        on_backups(lambda b: (b.rpc.backup_getrecoverydataCount -
                              b.backup.readCompletionCount) /
                   b.rpc.backup_getrecoverydataCount))


    efficiencySection = report.add(Section('Efficiency'))

    efficiencySection.line('recoverSegment CPU',
         (sum([m.master.recoverSegmentTicks / m.clockFrequency
              for m in masters]) * 1000 /
          sum([m.master.segmentReadCount
               for m in masters])),
        unit='ms avg')

    efficiencySection.line('Writing a segment',
        (sum([b.rpc.backup_writeTicks / b.clockFrequency
              for b in backups]) * 1000 /
        # Divide count by 2 since each segment does two writes:
        # one to open the segment and one to write the data.
        sum([b.rpc.backup_writeCount / 2
             for b in backups])),
        unit='ms avg')

    #efficiencySection.line('Filtering a segment',
    #    sum([b.backup.filterTicks / b.clockFrequency * 1000
    #         for b in backups]) /
    #    sum([b.backup.storageReadCount
    #         for b in backups]),
    #    unit='ms avg')

    efficiencySection.line('Memory bandwidth (backup copies)',
        on_backups(lambda b: (
            (b.backup.writeCopyBytes / 2**30) /
            (b.backup.writeCopyTicks / b.clockFrequency))),
        unit='GB/s',
        summaryFns=[AVG, MIN])

    networkSection = report.add(Section('Network Utilization'))
    networkSection.line('Aggregate',
        (sum([host.transport.transmit.byteCount
              for host in [coord] + masters + backups]) *
         8 / 2**30 / recoveryTime),
        unit='Gb/s',
        summaryFns=[AVG, FRAC(data.totalNodes*25)])

    networkSection.line('Master in',
        on_masters(lambda m: (m.transport.receive.byteCount * 8 / 2**30) /
                             recoveryTime),
        unit='Gb/s',
        summaryFns=[AVG, MIN, SUM])
    networkSection.line('Master out',
        on_masters(lambda m: (m.transport.transmit.byteCount * 8 / 2**30) /
                             recoveryTime),
        unit='Gb/s',
        summaryFns=[AVG, MIN, SUM])
    networkSection.line('Master out during replication',
        on_masters(lambda m: (m.master.replicationBytes * 8 / 2**30) /
                             (m.master.replicationTicks / m.clockFrequency)),
        unit='Gb/s',
        summaryFns=[AVG, MIN, SUM])
    networkSection.line('Master out during log sync',
        on_masters(lambda m: (m.master.logSyncBytes * 8 / 2**30) /
                             (m.master.logSyncTicks / m.clockFrequency)),
        unit='Gb/s',
        summaryFns=[AVG, MIN, SUM])

    networkSection.line('Backup in',
        on_backups(lambda b: (b.transport.receive.byteCount * 8 / 2**30) /
                             recoveryTime),
        unit='Gb/s',
        summaryFns=[AVG, MIN, SUM])
    networkSection.line('Backup out',
        on_backups(lambda b: (b.transport.transmit.byteCount * 8 / 2**30) /
                             recoveryTime),
        unit='Gb/s',
        summaryFns=[AVG, MIN, SUM])


    diskSection = report.add(Section('Disk Utilization'))
    diskSection.line('Effective bandwidth',
        on_backups(lambda b: (b.backup.storageReadBytes +
                              b.backup.storageWriteBytes) /
                             2**20 / recoveryTime),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])

    def active_bandwidth(b):
        totalBytes = b.backup.storageReadBytes + b.backup.storageWriteBytes
        totalTicks = b.backup.storageReadTicks + b.backup.storageWriteTicks
        return ((totalBytes / 2**20) /
                (totalTicks / b.clockFrequency))
    diskSection.line('Active bandwidth',
        on_backups(active_bandwidth),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])

    diskSection.line('Active bandwidth reading',
        on_backups(lambda b: (b.backup.storageReadBytes / 2**20) /
                             (b.backup.storageReadTicks / b.clockFrequency)),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])

    diskSection.line('Active bandwidth writing',
        on_backups(lambda b: (b.backup.storageWriteBytes / 2**20) /
                             (b.backup.storageWriteTicks / b.clockFrequency)),
        unit='MB/s',
        summaryFns=[AVG, MIN, SUM])

    diskSection.line('Disk active time',
        on_backups(lambda b: 100 * (b.backup.storageReadTicks +
                                    b.backup.storageWriteTicks) /
                             b.clockFrequency /
                             recoveryTime),
        unit='%')
    diskSection.line('Disk reading time',
        on_backups(lambda b: 100 * b.backup.storageReadTicks /
                             b.clockFrequency /
                             recoveryTime),
        unit='%')
    diskSection.line('Disk writing time',
        on_backups(lambda b: 100 * b.backup.storageWriteTicks /
                             b.clockFrequency /
                             recoveryTime),
        unit='%')

    backupSection = report.add(Section('Backup Events'))
    backupSection.line('Segments read',
        on_backups(lambda b: b.backup.storageReadCount))
    backupSection.line('Primary segments loaded',
        on_backups(lambda b: b.backup.primaryLoadCount))
    backupSection.line('Secondary segments loaded',
        on_backups(lambda b: b.backup.secondaryLoadCount))

    slowSection = report.add(Section('Slowest Servers'))

    slowest = maxTuple([
            [1e03 * (master.master.replicaManagerTicks -
             master.master.logSyncTicks) / master.clockFrequency,
             master.server] for master in masters])
    if slowest:
        slowSection.line('Backup opens, writes',
            slowest[0],
            summaryFns=[CUSTOM(slowest[1]),
                        CUSTOM('{0:.1f} ms'.format(slowest[0]))])

    slowest = maxTuple([
            [1e03 * master.master.segmentReadStallTicks /
             master.clockFrequency, master.server]
             for master in masters])
    if slowest:
        slowSection.line('Stalled reading segs from backups',
            slowest[0],
            summaryFns=[CUSTOM(slowest[1]),
                        CUSTOM('{0:.1f} ms'.format(slowest[0]))])

    slowest = minTuple([
            [(backup.backup.storageReadBytes / 2**20) / 
             (backup.backup.storageReadTicks / backup.clockFrequency),
             backup.server] for backup in backups
             if (backup.backup.storageReadTicks > 0)])
    if slowest:
        slowSection.line('Reading from disk',
            slowest[0],
            summaryFns=[CUSTOM(slowest[1]),
                        CUSTOM('{0:.1f} MB/s'.format(slowest[0]))])

    slowest = minTuple([
            [(backup.backup.storageWriteBytes / 2**20) / 
             (backup.backup.storageWriteTicks / backup.clockFrequency),
             backup.server] for backup in backups
             if backup.backup.storageWriteTicks])
    if slowest:
        slowSection.line('Writing to disk',
            slowest[0],
            summaryFns=[CUSTOM(slowest[1]),
                        CUSTOM('{0:.1f} MB/s'.format(slowest[0]))])

    tempSection = report.add(Section('Temporary Metrics'))
    for i in range(10):
        field = 'ticks{0:}'.format(i)
        points = [(host.serverId, host.temp[field] / host.clockFrequency)
                  for host in servers]
        if any(values(points)):
            tempSection.ms('temp.%s' % field,
                           points,
                           total=recoveryTime)
    for i in range(10):
        field = 'count{0:}'.format(i)
        points = [(host.serverId, host.temp[field])
                  for host in servers]
        if any(values(points)):
            tempSection.line('temp.%s' % field,
                             points)

    return report

def main():
    ### Parse command line options
    parser = OptionParser()
    parser.add_option('-r', '--raw',
        dest='raw', action='store_true',
        help='Print out raw data (helpful for debugging)')
    parser.add_option('-a', '--all',
        dest='all', action='store_true',
        help='Print out all raw data not just a sample')
    options, args = parser.parse_args()
    if len(args) > 0:
        recovery_dir = args[0]
    else:
        recovery_dir = 'logs/latest'

    data = parseRecovery(recovery_dir)

    if options.raw:
        if options.all:
            rawFull(data)
        else:
            rawSample(data)

    report = makeReport(data).jsonable()
    getDumpstr().print_report(report)

if __name__ == '__main__':
    sys.exit(main())
