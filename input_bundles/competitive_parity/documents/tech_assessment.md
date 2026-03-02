# Technical Assessment — Real-Time Co-Editing Architecture

**Prepared by:** Engineering Platform Team
**Date:** 2025-10-30
**Status:** Draft — for Product review

---

## Background

CollabDocs currently uses a pessimistic locking model backed by a PostgreSQL advisory lock and a Redis session store. The lock is acquired when a user opens a document in edit mode and released when they close it or after a 30-minute idle timeout. This model was chosen in 2022 for simplicity and consistency guarantees. It is now a competitive liability.

This document assesses two primary architectural approaches for real-time co-editing and provides a recommendation with tradeoffs.

---

## Approach 1: Operational Transformation (OT)

### How it works

OT treats each edit as an operation (insert character at position X, delete N characters at position Y). A central server sequences all incoming operations and transforms conflicting operations to ensure all clients converge to the same document state.

### Prior art

- Google Docs (in production at massive scale since ~2010)
- Competitor Y (CoEdit Pro)
- Microsoft Office Online

### Pros

- Well-understood algorithm with decades of production hardening
- Central server authority makes audit trails straightforward
- Familiar model for our existing server-side architecture (stateful sessions, PostgreSQL)
- Easier to implement permission checks (e.g., section-level locking for admin features)
- Good library support: ShareDB (Node.js), OT.js

### Cons

- Requires persistent, low-latency connection to the central OT server
- No offline support — clients must be connected to make changes
- Horizontal scaling of the OT server is non-trivial; requires sticky sessions or shared operation log
- At very high concurrency (>20 simultaneous editors) transformation complexity grows; known to cause latency spikes
- Implementing OT for rich-text (beyond plain text) requires significantly more complexity (paragraphs, formatting, tables)

### Estimated implementation effort

| Component | Estimate |
|-----------|----------|
| OT server (Node.js, ShareDB) | 4 weeks |
| Client integration (web) | 3 weeks |
| Presence / cursor sync | 2 weeks |
| Mobile client (iOS + Android) | 4 weeks |
| Migration from locking model | 2 weeks |
| Testing + hardening | 3 weeks |
| **Total** | **~18 weeks** |

---

## Approach 2: CRDT (Conflict-free Replicated Data Types)

### How it works

CRDTs define a document as a data structure where any two states can always be merged without conflict. Each client holds its own full copy of the document. Changes are broadcast as diffs; all clients independently merge diffs and converge to the same state. No central sequencer is required.

### Prior art

- Competitor X (LiveWrite) — uses Yjs, an open-source CRDT library
- Figma (multiplayer design tool) — CRDT-inspired approach
- Notion (partial CRDT implementation for blocks)
- Apple Notes (offline sync)

### Pros

- Native offline support: edits queue locally and sync on reconnect
- No single point of failure for the sync server (can be stateless relay)
- Scales horizontally with minimal coordination overhead
- Convergence is mathematically guaranteed — no merge conflicts surface to users
- Active open-source ecosystem: **Yjs** (most mature, MIT license), Automerge

### Cons

- More complex client-side logic: every client maintains full document state
- Initial document load can be slow for very large documents (full state transfer)
- CRDT history grows unboundedly without garbage collection — requires periodic compaction
- Rich-text CRDTs (Yjs has `y-prosemirror`, `y-quill`) require adapting our existing Slate.js editor
- Harder to implement admin section-locking (our differentiating feature) — requires custom extension
- Less familiar to the team; steeper learning curve
- Debugging convergence issues is harder than OT

### Estimated implementation effort

| Component | Estimate |
|-----------|----------|
| Yjs integration + sync server (y-websocket) | 3 weeks |
| Slate.js → y-slate binding | 4 weeks |
| Presence / cursor sync (Yjs awareness API) | 1 week |
| Mobile client (iOS + Android) | 5 weeks |
| Migration from locking model + CRDT history bootstrap | 3 weeks |
| Admin section-locking extension | 2 weeks |
| Testing + hardening + compaction | 3 weeks |
| **Total** | **~21 weeks** |

---

## Approach 3: Hybrid (Locking → OT Phased Migration)

### Description

Phase 1: Replace pessimistic locking with an **optimistic locking + last-write-wins** model as a fast interim fix. This eliminates the lock-wait frustration immediately while the full OT implementation is built. Users see a conflict notification if their edit was overwritten, and can recover from version history.

Phase 2: Ship full OT-based real-time co-editing as the permanent solution.

### Pros

- Phase 1 ships in ~3 weeks and directly addresses the top UX complaint
- Buys time to build OT properly without competitive pressure forcing a rushed CRDT migration
- Phase 1 is entirely server-side; no client changes

### Cons

- Phase 1 still has silent data loss risk (mitigated but not eliminated)
- Two migrations instead of one; technical debt in Phase 1
- Does not deliver the "live editing" experience that customers are asking for until Phase 2

### Estimated effort

- Phase 1: ~3 weeks
- Phase 2: ~18 weeks (same as Approach 1)
- **Total: ~21 weeks** (but Phase 1 value delivered at 3 weeks)

---

## Engineering Recommendation

The team recommends **Approach 2 (CRDT / Yjs)** for the following reasons:

1. **Offline support** is a frequently requested feature that OT cannot provide; CRDT delivers it as a byproduct
2. **Yjs is battle-tested** in production at Competitor X and multiple open-source projects; we would not be building CRDT from scratch
3. **Stateless sync relay** is easier to operate and scale than an OT server with sticky sessions
4. **Mobile-first**: CRDT handles intermittent mobile connectivity naturally; OT requires connection recovery logic
5. The additional 3-week estimate over OT is largely in the Slate.js binding, which also delivers editor performance improvements

**Risk mitigation**: We recommend a 2-week proof-of-concept spike on `y-slate` integration before committing to the full timeline, to validate the Slate.js binding complexity.

**Secondary recommendation**: Regardless of approach chosen, implement **presence indicators** (cursors + avatars) first — they are independent of the conflict resolution engine and can ship in ~3 weeks, providing visible progress to at-risk enterprise accounts.

---

## Open Questions for Product

1. Should admin section-locking be preserved in the MVP of co-editing, or deferred to V2? (Impacts CRDT extension scope by ~2 weeks)
2. What is the maximum simultaneous editor count we need to support at launch? (Impacts CRDT compaction strategy)
3. Is offline support a V1 requirement or V2? (Would allow OT to remain competitive if offline is not urgent)
4. Should the co-editing feature be available on all tiers, or gated to paid/enterprise? (No architectural impact, but affects rollout strategy)
