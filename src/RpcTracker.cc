/* Copyright (c) 2014-2015 Stanford University
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

#include "RamCloud.h"
#include "RpcTracker.h"

namespace RAMCloud {

/**
 * Clean up allocated resources.
 */
RpcTracker::~RpcTracker()
{
}

/**
 * Mark the receipt of the result for an RPC.
 *
 * \param rpcId
 *      The id of an Rpc.
 */
void
RpcTracker::rpcFinished(uint64_t rpcId)
{
    // Only need to mark receipt if the rpcId is inside window.
    if (rpcId >= firstMissing && rpcId < firstMissing + windowSize) {
        rpcs[rpcId & indexMask] = NULL;
        if (firstMissing == rpcId) {
            firstMissing++;
            while (!rpcs[firstMissing & indexMask] && firstMissing < nextRpcId)
                firstMissing++;
        }
    }
}

/**
 * Gets a unique RPC id for new Tracked RPC.  This method may block waiting for
 * the oldest TrackedRpc to complete if it is running too far behind.  This
 * effectively bounds the number of outstanding requests a client may have.
 *
 * \param ptr
 *      Pointer to TrackedRpc to which we assign a new rpcId.
 *
 * \return
 *      The id for new RPC.
 */
uint64_t
RpcTracker::newRpcId(TrackedRpc* ptr)
{
    assert(ptr != NULL);
    uint32_t finishFailures = 0;
    while (firstMissing + windowSize <= nextRpcId) {
        RAMCLOUD_CLOG(NOTICE, "Waiting for response of RPC with id: %ld",
                      firstMissing);
        TrackedRpc* oldest = oldestOutstandingRpc();
        bool finished = oldest->tryFinish();
        if (!finished) {
            ++finishFailures;
            if (finishFailures >= MAX_TRY_FINISH_FAILURES) {
                // This should NOT happen, but we give up and assign the intended nextRpcId if it does
                RAMCLOUD_LOG(WARNING, "Encountered %d failures on oldest RPC to try and finish",
                             MAX_TRY_FINISH_FAILURES);
                break;
            }
        }
    }
    if (firstMissing + windowSize <= nextRpcId) {
        // This should NOT happen, but we press onwards and assign the intended nextRpcId anyhow.
        // Because this code is in rc-client, we try to avoid crashing the external application
        // if it's just a matter of an RPC taking too long and needing more time.
        RAMCLOUD_LOG(WARNING, "firstMissing(%ld) + windowSize(%d) <= nextRpcId(%ld)",
                     firstMissing, windowSize, nextRpcId);
    }
    rpcs[nextRpcId & indexMask] = ptr;
    return nextRpcId++;
}

/**
 * Gets an atomic block of unique RPC ids.
 *
 * Id blocks requested via this method are released atomically by calling
 * rpcFinished on the first id in the block.
 *
 * This method may block waiting for the oldest TrackedRpc to complete if it is
 * running too far behind.  This effectively bounds the number of outstanding
 * requests a client may have.
 *
 * Used to allocate a blocks of RPC ids for transactions.
 *
 * \param ptr
 *      Pointer to TrackedRpc to which we assign a new block of RPC ids.
 * \param size
 *      Number of new RPC ids that should be allocated.
 * \return
 *      First RPC id in the block of new RPC ids.
 */
uint64_t
RpcTracker::newRpcIdBlock(TrackedRpc* ptr, size_t size)
{
    assert(ptr != NULL);
    uint32_t finishFailures = 0;
    while (firstMissing + windowSize <= nextRpcId) {
        RAMCLOUD_CLOG(NOTICE, "Waiting for response of RPC with id: %ld",
                      firstMissing);
        TrackedRpc* oldest = oldestOutstandingRpc();
        bool finished = oldest->tryFinish();
        if (!finished) {
            ++finishFailures;
            if (finishFailures >= MAX_TRY_FINISH_FAILURES) {
                // This should NOT happen, but we give up and assign the intended nextRpcId if it does
                RAMCLOUD_LOG(WARNING, "Encountered %d failures on oldest RPC to try and finish",
                             MAX_TRY_FINISH_FAILURES);
                break;
            }
        }
    }
    if (firstMissing + windowSize <= nextRpcId) {
        // This should NOT happen, but we press onwards and assign the intended nextRpcId anyhow.
        // Because this code is in rc-client, we try to avoid crashing the external application
        // if it's just a matter of an RPC taking too long and needing more time.
        RAMCLOUD_LOG(WARNING, "firstMissing(%ld) + windowSize(%d) <= nextRpcId(%ld)",
                     firstMissing, windowSize, nextRpcId);
    }
    rpcs[nextRpcId & indexMask] = ptr;
    uint64_t blockRpcId = nextRpcId;
    nextRpcId += size;
    return blockRpcId;
}

/**
 * Gets the current acknowledgment id, which indicates RPCs with id smaller
 * than this number have all received results.
 *
 * \return
 *      The ackId value to be sent with new RPC.
 */
uint64_t
RpcTracker::ackId()
{
    return firstMissing - 1;
}

/**
 * Return the pointer to the oldest outstanding linearizable RPC.
 * \return
 *      Pointer to linearizable RPC wrapper with smallest rpdId.
 */
RpcTracker::TrackedRpc*
RpcTracker::oldestOutstandingRpc()
{
    assert(rpcs[firstMissing & indexMask]);
    return rpcs[firstMissing & indexMask];
}

} // namespace RAMCloud
