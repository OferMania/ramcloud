/* Copyright (c) 2010-2017 Stanford University
 *
 * Permission to use, copy, modify, and distribute this software for any
 * purpose with or without fee is hereby granted, provided that the above
 * copyright notice and this permission notice appear in all copies.
 *
 * THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR(S) DISCLAIM ALL WARRANTIES
 * WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
 * MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL AUTHORS BE LIABLE FOR
 * ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
 * WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
 * ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
 * OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
 */

#ifndef RAMCLOUD_RAMCLOUDTIMED_H
#define RAMCLOUD_RAMCLOUDTIMED_H

#include "CoordinatorRpcWrapper.h"
#include "IndexRpcWrapper.h"
#include "LinearizableObjectRpcWrapper.h"
#include "ObjectRpcWrapper.h"
#include "RamCloud.h"

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wconversion"
#pragma GCC diagnostic ignored "-Weffc++"
#include "LogMetrics.pb.h"
#include "ServerConfig.pb.h"
#include "ServerStatistics.pb.h"
#pragma GCC diagnostic pop

namespace RAMCloud {
class ClientLeaseAgent;
class ClientTransactionManager;
class MultiIncrementObject;
class MultiReadObject;
class MultiRemoveObject;
class MultiWriteObject;
class ObjectFinder;
class RpcTracker;

/**
 * The RamCloudTimed class provides synchronous-with-timeout methods analogous
 * to the totally synchronous ones in RamCloud.  The method signatures are
 * the same; this class has-a RamCloud* that points a base object it can
 * use, and also remembers a max time to wait and the call's ultimate
 * status.  Any call to an RamCloudTimed method should check getStatus() for 
 * RAMCloud::STATUS_OK before using any returned value.  A status of
 * RAMCloud::STATUS_TIMEOUT means the returned value is undefined.
 *
 * Each RamCloudTimed object provides access to a particular RAMCloud cluster;
 * all of the RAMCloud RPC requests appear as methods on this object.
 *
 * In multi-threaded clients there must be a separate RamCloudTimed object for
 * each thread; as of 5/2012 these objects are not thread-safe.
 *
 */

class RamCloudTimed {
  public:
    uint64_t createTable(const char* name, uint64_t msec, uint32_t serverSpan = 1);
    void dropTable(const char* name, uint64_t msec);
    uint64_t enumerateTable(uint64_t tableId, bool keysOnly,
            uint64_t tabletFirstHash, Buffer& state, Buffer& objects,
            uint64_t msec);
    uint64_t getTableId(const char* name, uint64_t msec);

    void poll();
    explicit RamCloudTimed(RamCloud* ramcloud);
    virtual ~RamCloudTimed();

    Status getStatus() {return status;};

  private:
    /// Overall client state information.
    RamCloud* ramcloud;

    /// Status of time-limited call.
    Status status;

    DISALLOW_COPY_AND_ASSIGN(RamCloudTimed);
};

/**
 * Encapsulates the state of a RamCloudTimed::createTable operation,
 * allowing it to execute asynchronously.
 */
class CreateTableTimedRpc : public CoordinatorRpcWrapper {
  public:
    CreateTableTimedRpc(RamCloud* ramcloud, const char* name,
            uint32_t serverSpan);
    ~CreateTableTimedRpc() {}
    uint64_t wait(uint64_t msec, Status* pStatus);

  PRIVATE:
    DISALLOW_COPY_AND_ASSIGN(CreateTableTimedRpc);
};

/**
 * Encapsulates the state of a RamCloudTimed::dropTable operation,
 * allowing it to execute asynchronously.
 */
class DropTableTimedRpc : public CoordinatorRpcWrapper {
  public:
    DropTableTimedRpc(RamCloud* ramcloud, const char* name);
    ~DropTableTimedRpc() {}
    /// \copydoc RpcWrapper::docForWait
    void wait(uint64_t msec, Status* pStatus);

  PRIVATE:
    DISALLOW_COPY_AND_ASSIGN(DropTableTimedRpc);
};

/**
 * Encapsulates the state of a RamCloudTimed::enumerateTable
 * request, allowing it to execute asynchronously.
 */
class EnumerateTableTimedRpc : public ObjectRpcWrapper {
  public:
    EnumerateTableTimedRpc(RamCloud* ramcloud, uint64_t tableId, bool keysOnly,
            uint64_t tabletFirstHash, Buffer& iter, Buffer& objects);
    ~EnumerateTableTimedRpc() {}
    uint64_t wait(Buffer& nextIter, uint64_t msec, Status* pStatus);

  PRIVATE:
    DISALLOW_COPY_AND_ASSIGN(EnumerateTableTimedRpc);
};

/**
 * Encapsulates the state of a RamCloudTimed operation,
 * allowing it to execute asynchronously.
 */
class GetTableIdTimedRpc : public CoordinatorRpcWrapper {
  public:
    GetTableIdTimedRpc(RamCloud* ramcloud, const char* name);
    ~GetTableIdTimedRpc() {}
    uint64_t wait(uint64_t msec, Status* pStatus);

  PRIVATE:
    DISALLOW_COPY_AND_ASSIGN(GetTableIdTimedRpc);
};

} // namespace RAMCloud

#endif // RAMCLOUD_RAMCLOUDTIMED_H
