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

#include <stdarg.h>

#include "RamCloudTimed.h"
#include "ClientLeaseAgent.h"
#include "ClientTransactionManager.h"
#include "CoordinatorClient.h"
#include "CoordinatorSession.h"
#include "Dispatch.h"
#include "LinearizableObjectRpcWrapper.h"
#include "FailSession.h"
#include "MasterClient.h"
#include "MultiIncrement.h"
#include "MultiRead.h"
#include "MultiRemove.h"
#include "MultiWrite.h"
#include "Object.h"
#include "ObjectFinder.h"
#include "ProtoBuf.h"
#include "RpcTracker.h"
#include "ShortMacros.h"
#include "TimeTrace.h"

namespace RAMCloud {

/**
 * == NOTE ==
 *   This file implements the synchronous-with-timeout flavors of Ramcloud
 *   object methods declared in RamCloudTimed.h, as well as the RPC wrapper objects
 *   to support them.
 *   Purely synchronous (and simpler, but blocking) flavors are in RamCloud.cc.
 */

/**
 * Constructor for a timed client object.  Note that it has-a pointer to a
 * vanilla RamCloud object.
 *
 * \param ramcloud
 *      Overall information about the calling client.
 */
RamCloudTimed::RamCloudTimed(RamCloud* ramcloud)
    : ramcloud(ramcloud)
    , status(STATUS_SERVER_NOT_UP)
{
}

RamCloudTimed::~RamCloudTimed()
{
}

/**
 * Create a new table.
 *
 * \param name
 *      Name for the new table (NULL-terminated string).
 * \param msec
 *      Max time to wait before canceling the RPC, in milliseconds.
 * \param serverSpan
 *      The number of servers across which this table will be divided
 *      (defaults to 1). Keys within the table will be evenly distributed
 *      to this number of servers according to their hash. This is a temporary
 *      work-around until tablet migration is complete; until then, we must
 *      place tablets on servers statically.
 *
 * \return
 *      The return value is an identifier for the created table; this is
 *      used instead of the table's name for most RAMCloud operations
 *      involving the table.
 *
 * \throw ClientException
 *       Thrown on invalid parameter or if an unrecoverable error occurred
 *       while communicating with the target server.
 */
uint64_t
RamCloudTimed::createTable(const char* name, uint64_t msec, uint32_t serverSpan)
{
    CreateTableTimedRpc rpc(ramcloud, name, serverSpan);
    return rpc.wait(msec, &status);
}

/**
 * Constructor for CreateTableTimedRpc: initiates an RPC in the same way as
 * #RamCloudTimed::createTable, but returns once the RPC has been initiated,
 * without waiting for it to complete.
 *
 * \param ramcloud
 *      The RAMCloud object that governs this RPC.
 * \param name
 *      Name for the new table (NULL-terminated string).
 * \param serverSpan
 *      The number of servers across which this table will be divided
 *      (defaults to 1).
 */
CreateTableTimedRpc::CreateTableTimedRpc(RamCloud* ramcloud,
        const char* name, uint32_t serverSpan)
    : CoordinatorRpcWrapper(ramcloud->clientContext,
            sizeof(WireFormat::CreateTable::Response))
{
    uint32_t length = downCast<uint32_t>(strlen(name) + 1);
    WireFormat::CreateTable::Request* reqHdr(
            allocHeader<WireFormat::CreateTable>());
    reqHdr->nameLength = length;
    reqHdr->serverSpan = serverSpan;
    request.append(name, length);
    send();
}

/**
 * Wait for the RPC to complete, and return the same results as
 * #RamCloudTimed::createTable.
 *
 * \param msec
 *      Max time to wait before canceling the RPC, in milliseconds.
 * \param pStatus
 *      On output, has the status of the RPC, likely either STATUS_OK or STATUS_TIMEOUT.
 *
 * \return
 *      The return value is an identifier for the created table, if STATUS_OK.
 */
uint64_t
CreateTableTimedRpc::wait(uint64_t msec, Status* pStatus)
{
    uint64_t abortTime = Cycles::rdtsc() + Cycles::fromMilliseconds(msec);
    bool     respValid = waitInternal(context->dispatch, abortTime);

    if (respValid)
    {
        const WireFormat::CreateTable::Response* respHdr(
                getResponseHeader<WireFormat::CreateTable>());
        *pStatus = respHdr->common.status;
        if (respHdr->common.status != STATUS_OK)
            ClientException::throwException(HERE, respHdr->common.status);
        return respHdr->tableId;
    }
    else
    {
        cancel();
        *pStatus = STATUS_TIMEOUT;
        return 0ULL;
    }
}

/**
 * Delete a table.
 *
 * All objects in the table are implicitly deleted, along with any
 * other information associated with the table.  If the table does
 * not currently exist then the operation returns successfully without
 * actually doing anything.
 *
 * \param name
 *      Name of the table to delete (NULL-terminated string).
 * \param msec
 *      Max time to wait before canceling the RPC, in milliseconds.
 *
 * \throw ClientException
 *       Thrown on invalid parameter or if an unrecoverable error occurred
 *       while communicating with the target server.
 */
void
RamCloudTimed::dropTable(const char* name, uint64_t msec)
{
    DropTableTimedRpc rpc(ramcloud, name);
    rpc.wait(msec, &status);
}

/**
 * Constructor for DropTableTimedRpc: initiates an RPC in the same way as
 * #RamCloudTimed::dropTable, but returns once the RPC has been initiated,
 * without waiting for it to complete.
 *
 * \param ramcloud
 *      The RAMCloud object that governs this RPC.
 * \param name
 *      Name of the table to delete (NULL-terminated string).
 */
DropTableTimedRpc::DropTableTimedRpc(RamCloud* ramcloud, const char* name)
    : CoordinatorRpcWrapper(ramcloud->clientContext,
            sizeof(WireFormat::DropTable::Response))
{
    uint32_t length = downCast<uint32_t>(strlen(name) + 1);
    WireFormat::DropTable::Request* reqHdr(
            allocHeader<WireFormat::DropTable>());
    reqHdr->nameLength = length;
    request.append(name, length);
    send();
}

/**
 * Wait for the RPC to complete, and return the same results as
 * #RamCloudTimed::dropTable.
 *
 * \param msec
 *      Max time to wait before canceling the RPC, in milliseconds.
 * \param pStatus
 *      On output, has the status of the RPC, likely either STATUS_OK or STATUS_TIMEOUT.
 *
 * \return
 *      The return value is an identifier for the created table.
 */
void
DropTableTimedRpc::wait(uint64_t msec, Status* pStatus)
{
    uint64_t abortTime = Cycles::rdtsc() + Cycles::fromMilliseconds(msec);
    bool     respValid = waitInternal(context->dispatch, abortTime);

    if (respValid)
    {
        *pStatus = responseHeader->status;
    }
    else
    {
        cancel();
        *pStatus = STATUS_TIMEOUT;
    }
    return;
}

/**
 * This method provides the core of table enumeration. It is invoked
 * repeatedly to enumerate a table; each invocation returns the next
 * set of objects (from a particular tablet stored on a particular server)
 * and also provides information about where we are in the overall
 * enumeration, which is used in future invocations of this method.
 *
 * This method is meant to be called from TableEnumerator and should not
 * normally be used directly by applications.
 *
 * \param tableId
 *      The table being enumerated (return value from a previous call
 *      to getTableId) .
 * \param keysOnly
 *      False means that full objects are returned, containing both keys
 *      and data. True means that the returned objects have
 *      been truncated so that the object data (normally the last
 *      field of the object) is omitted. Note: the size field in the
 *      log record headers is unchanged, which means it does not
 *      exist corresponding to the length of the log record.
 * \param tabletFirstHash
 *      Where to continue enumeration. The caller should provide zero
 *       the initial call. On subsequent calls, the caller should pass
 *       the return value from the previous call.
 * \param[in,out] state
 *      Holds the state of enumeration; opaque to the caller.  On the
 *      initial call this Buffer should be empty. At the end of each
 *      call the contents are modified to hold the current state of
 *      the enumeration. The caller must return the new value each
 *      time this method is invoked.
 * \param[out] objects
 *      After a successful return, this buffer will contain zero or
 *      more objects from the requested tablet. If zero objects are
 *      returned, then there are no more objects remaining in the
 *      tablet. When this happens, the return value will be set to
 *      point to the next tablet, or will be set to zero if this is
 *      the end of the entire table.
 * \param msec
 *      Max time to wait before canceling the RPC, in milliseconds.
 *
 * \return
 *       The return value is a key hash indicating where to continue
 *       enumeration (the starting key hash for the tablet where
 *       enumeration should continue); it must be passed to the next call
 *       to this method as the \a tabletFirstHash argument.  A zero
 *       return value, combined with no objects returned in \a objects,
 *       means that enumeration has finished.
 */
uint64_t
RamCloudTimed::enumerateTable(uint64_t tableId, bool keysOnly,
        uint64_t tabletFirstHash, Buffer& state, Buffer& objects,
        uint64_t msec)
{
    EnumerateTableTimedRpc rpc(ramcloud, tableId, keysOnly,
                          tabletFirstHash, state, objects);
    return rpc.wait(state, msec, &status);
}

/**
 * Constructor for EnumerateTableTimedRpc: initiates an RPC in the same way as
 * #RamCloudTimed::enumerateTable, but returns once the RPC has been initiated,
 * without waiting for it to complete.
 *
 * \param ramcloud
 *      The RAMCloud object that governs this RPC.
 * \param tableId
 *      The table being enumerated (return value from a previous call
 *      to getTableId) .
 * \param keysOnly
 *      False means that full objects are returned, containing both keys
 *      and data. True means that the returned objects have
 *      been truncated so that the object data (normally the last
 *      field of the object) is omitted. Note: the size field in the
 *      log record headers is unchanged, which means it does not
 *      exist corresponding to the length of the log record.
 * \param tabletFirstHash
 *      Where to continue enumeration. The caller should provide zero
*       the initial call. On subsequent calls, the caller should pass
*       the return value from the previous call.
 * \param state
 *      Holds the state of enumeration; opaque to the caller.  On the
 *      initial call this Buffer should be empty. In subsequent calls
 *      this must contain the information returned by \c wait from
 *      the previous call.
 * \param[out] objects
 *      After a successful return, this buffer will contain zero or
 *      more objects from the requested tablet.
 */
EnumerateTableTimedRpc::EnumerateTableTimedRpc(RamCloud* ramcloud, uint64_t tableId,
        bool keysOnly, uint64_t tabletFirstHash, Buffer& state, Buffer& objects)
    : ObjectRpcWrapper(ramcloud->clientContext, tableId, tabletFirstHash,
            sizeof(WireFormat::Enumerate::Response), &objects)
{
    WireFormat::Enumerate::Request* reqHdr(
            allocHeader<WireFormat::Enumerate>());
    reqHdr->tableId = tableId;
    reqHdr->keysOnly = keysOnly;
    reqHdr->tabletFirstHash = tabletFirstHash;
    reqHdr->iteratorBytes = state.size();
    for (Buffer::Iterator it(&state); !it.isDone(); it.next())
        request.append(it.getData(), it.getLength());
    send();
}

/**
 * Wait for an enumerate RPC to complete, and return the same results as
 * #RamCloudTimed::enumerate.
 *
 * \param[out] state
 *      Will be filled in with the current state of the enumeration as of
 *      this method's return.  Must be passed back to this class as the
 *      \a iter parameter to the constructor when retrieving the next
 *      objects.
 * \param msec
 *      Max time to wait before canceling the RPC, in milliseconds.
 * \param pStatus
 *      On output, has the status of the RPC, likely either STATUS_OK or STATUS_TIMEOUT.
 *
 * \return
 *       The return value is a key hash indicating where to continue
 *       enumeration (the starting key hash for the tablet where
 *       enumeration should continue); it must be passed to the constructor
 *       as the \a tabletFirstHash argument when retrieving the next
 *       objects.  In addition, zero or more objects from the enumeration
 *       will be returned in the \a objects Buffer specified to the
 *       constructor.  A zero return value, combined with no objects
 *       returned in \a objects, means that all objects in the table have
 *       been enumerated.
 *
 */
uint64_t
EnumerateTableTimedRpc::wait(Buffer& state, uint64_t msec, Status* pStatus)
{
    uint64_t abortTime = Cycles::rdtsc() + Cycles::fromMilliseconds(msec);
    bool respValid = waitInternal(context->dispatch, abortTime);

    if (respValid)
    {
        *pStatus = responseHeader->status;
        if (responseHeader->status != STATUS_OK)
            ClientException::throwException(HERE, responseHeader->status);

        const WireFormat::Enumerate::Response* respHdr(
                getResponseHeader<WireFormat::Enumerate>());
        uint64_t result = respHdr->tabletFirstHash;

        // Copy iterator from response into nextIter buffer.
        uint32_t iteratorBytes = respHdr->iteratorBytes;
        state.reset();
        if (iteratorBytes != 0) {
            response->copy(
                    downCast<uint32_t>(sizeof(*respHdr) + respHdr->payloadBytes),
                    iteratorBytes, state.alloc(iteratorBytes));
        }

        // Truncate the front and back of the response buffer, leaving just the
        // objects (the response buffer is the \c objects argument from
        // the constructor).
        assert(response->size() == sizeof(*respHdr) +
                respHdr->iteratorBytes + respHdr->payloadBytes);
        response->truncateFront(sizeof(*respHdr));
        response->truncate(response->size() - respHdr->iteratorBytes);

        return result;
    }
    else
    {
        cancel();
        *pStatus = STATUS_TIMEOUT;
        return 0ULL;
    }
}

/**
 * Given the name of a table, return the table's unique identifier, which
 * is used to access the table.
 *
 * \param name
 *      Name of the desired table (NULL-terminated string).
 * \param msec
 *      Max time to wait before canceling the RPC, in milliseconds.
 *
 * \return
 *      The return value is an identifier for the table; this is used
 *      instead of the table's name for most RAMCloud operations
 *      involving the table.
 *
 * \exception TableDoesntExistException
 */
uint64_t
RamCloudTimed::getTableId(const char* name, uint64_t msec)
{
    GetTableIdTimedRpc rpc(ramcloud, name);
    return rpc.wait(msec, &status);
}

/**
 * Constructor for GetTableIdTimedRpc: initiates an RPC in the same way as
 * #RamCloudTimed::GetTableIdTimed, but returns once the RPC has been initiated,
 * without waiting for it to complete.
 *
 * \param ramcloud
 *      The RAMCloud object that governs this RPC.
 * \param name
 *      Name of the desired table (NULL-terminated string).
 */
GetTableIdTimedRpc::GetTableIdTimedRpc(RamCloud* ramcloud,
        const char* name) 
    : CoordinatorRpcWrapper(ramcloud->clientContext,
            sizeof(WireFormat::GetTableId::Response))
{
    uint32_t length = downCast<uint32_t>(strlen(name) + 1);
    WireFormat::GetTableId::Request* reqHdr(
            allocHeader<WireFormat::GetTableId>());
    reqHdr->nameLength = length;
    request.append(name, length);
    send();
}

/**
 * Wait for a GetTableIdTimedRpc RPC to complete, and return the same results as
 * #RamCloudTimed::GetTableIdTimed.
 *
 * \param msec
 *      Max time to wait before canceling the RPC, in milliseconds.
 * \param pStatus
 *      On output, has the status of the RPC, likely either STATUS_OK or STATUS_TIMEOUT.
 *
 * \return
 *      The return value is an identifier for the table.
 *
 * \exception TableDoesntExistException
 */
uint64_t
GetTableIdTimedRpc::wait(uint64_t msec, Status* pStatus)
{
    uint64_t abortTime = Cycles::rdtsc() + Cycles::fromMilliseconds(msec);
    bool respValid     = waitInternal(context->dispatch, abortTime);

    if (respValid)
    {
        const WireFormat::GetTableId::Response* respHdr(
                getResponseHeader<WireFormat::GetTableId>());
        *pStatus = respHdr->common.status;
        if (respHdr->common.status != STATUS_OK)
            ClientException::throwException(HERE, respHdr->common.status);
        return respHdr->tableId;
    }
    else
    {
        cancel();
        *pStatus = STATUS_TIMEOUT;
        return 0ULL;
    }
}

}  // namespace RAMCloud
