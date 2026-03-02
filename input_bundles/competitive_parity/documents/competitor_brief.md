# Competitive Brief — Real-Time Co-Editing

**Prepared by:** Product Strategy
**Date:** 2025-11-01
**Distribution:** Internal — Product & Engineering

---

## Overview

Two competitors have shipped real-time co-editing in 2025. This brief summarizes their approaches, feature sets, and known limitations to inform CollabDocs' implementation strategy.

---

## Competitor X — "LiveWrite"

**Launch Date:** October 15, 2025
**Positioning:** "Edit together, in real time, on any device"
**Pricing:** Included in all paid tiers (no add-on cost)

### Feature Set (as of November 2025)

| Feature | Status |
|---------|--------|
| Simultaneous multi-user editing | ✅ Live |
| Presence avatars (up to 8 users) | ✅ Live |
| Per-user cursor and selection highlighting | ✅ Live |
| Real-time comment threads | ✅ Live |
| Conflict-free concurrent edits (CRDT-based) | ✅ Live |
| Offline editing with sync-on-reconnect | ✅ Live |
| Mobile (iOS + Android) | ✅ Live |
| Version history with per-user attribution | ✅ Live |
| Granular edit permissions (view/comment/edit) | ✅ Live |
| @mentions in document body | ✅ Live |
| Guest access (no account required) | ❌ Not available |
| Document templates with live collaboration | ⚠️ Beta |

### Technical Approach (inferred from engineering blog)

Competitor X uses a **CRDT (Conflict-free Replicated Data Type)** implementation — specifically a variant of the Yjs framework for the document model, with a proprietary sync server over WebSocket. Key properties:
- Every client holds the full document state; changes are merged automatically
- No central lock authority; any client can write at any time
- Convergence is guaranteed — all clients will reach the same state
- Offline edits are queued and merged on reconnect

**Known limitations observed:**
- Presence is limited to 8 simultaneous users (beyond 8, avatars collapse to a count)
- Cursor positions occasionally jump for 200–400ms during high-concurrency bursts
- Large documents (>100 pages) show lag on initial load for collaborative sessions
- No conflict UI shown to users — all merges are automatic (can confuse users when content appears to rearrange)

### Go-to-Market

- Announced via a "State of Collaboration 2025" report targeting enterprise buyers
- Direct ad campaigns targeting CollabDocs and Google Docs users on LinkedIn
- Case study featuring a 500-person law firm that switched from a locking-model tool
- Free 30-day trial with no credit card for teams of any size

---

## Competitor Y — "CoEdit Pro"

**Launch Date:** March 2024 (18 months ahead of CollabDocs)
**Positioning:** "Enterprise-grade real-time editing with admin controls"
**Pricing:** Add-on tier at +$8/user/month

### Feature Set (as of November 2025)

| Feature | Status |
|---------|--------|
| Simultaneous multi-user editing | ✅ Live |
| Presence avatars (unlimited) | ✅ Live |
| Per-user cursor highlighting | ✅ Live |
| Conflict resolution UI (explicit merge prompts) | ✅ Live |
| Operational Transformation (OT) engine | ✅ Live |
| Offline editing | ❌ Not available |
| Mobile (iOS only) | ✅ Live — Android in beta |
| Admin controls (lock sections, restrict co-editors) | ✅ Live |
| Audit log of all real-time edits | ✅ Live |
| SSO integration | ✅ Live |

### Technical Approach

Competitor Y uses **Operational Transformation (OT)** — the same fundamental approach as Google Docs. OT requires a central server to sequence operations from multiple clients, ensuring consistency.

**Known limitations:**
- Requires persistent server connection; no offline support
- Scalability challenges at very high concurrency (>20 simultaneous editors) — known from engineering job postings referencing "OT scalability work"
- Conflict resolution UI surfaces merge prompts that some users find confusing
- Android app still in beta after 6 months

### Positioning vs. Competitor X

Competitor Y targets regulated industries (finance, legal, healthcare) that need audit trails and admin controls. They are not competing on consumer-friendliness — their conflict UI is more explicit and their pricing signals enterprise.

---

## Google Docs (Benchmark)

Google Docs remains the gold standard for real-time co-editing, but is not a direct competitor for CollabDocs' positioning (document management + workflow vs. freeform document creation).

Key features relevant as benchmarks:
- OT-based real-time editing, unlimited simultaneous users
- Named cursor highlighting, presence avatars
- Comment threads with @mentions
- Suggestion mode (tracked changes)
- Full offline support via Chrome extension
- Mobile (iOS + Android) — mature implementations

**Differentiation opportunity:** Google Docs lacks document workflow features (approval chains, structured templates, version gating) that are CollabDocs' core strength.

---

## Competitive Gap Summary

| Capability | CollabDocs | Competitor X | Competitor Y | Google Docs |
|------------|-----------|--------------|--------------|-------------|
| Real-time co-editing | ❌ | ✅ | ✅ | ✅ |
| Presence indicators | ❌ | ✅ | ✅ | ✅ |
| Conflict resolution | ❌ | Auto (CRDT) | Manual (OT) | Auto (OT) |
| Offline support | ❌ | ✅ | ❌ | ✅ |
| Mobile collaboration | ❌ | ✅ | Partial | ✅ |
| Document workflow | ✅ | ❌ | Partial | ❌ |
| Admin section locking | ✅ | ❌ | ✅ | ❌ |
| Audit trail | ✅ | ❌ | ✅ | Partial |

**Key insight:** CollabDocs leads on workflow and governance features. The real-time collaboration gap is the only critical feature area where we trail all three competitors. Closing this gap while preserving our workflow differentiation is the strategic priority.
