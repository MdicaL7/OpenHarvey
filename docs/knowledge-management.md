# Personal and organization knowledge

The Knowledge settings page at `/knowledge` contains personal preferences,
organization rules and templates, cases and decisions, a pending proposal
inbox, source imports, and (for platform administrators) member assignment.
Counterparties are an exact-identity filter, not another knowledge category.

Imported counterparty references are resolved within the current organization:
an active record ID, exact business identifier, or exact name/alias may match.
An ambiguous or missing reference stays on the pending proposal and requires
human selection before publication; it is never broadened to all counterparties.
The editor displays names and submits record IDs, with effective dates available
for review. Partial edits preserve other metadata and full source records
(including hashes, block positions and multiline excerpts). An omitted field
is unchanged; a metadata key set to null explicitly clears that key. Replacing
or removing evidence is an explicit form operation.

## Access and confirmation

Existing active platform administrators are bootstrapped as maintainers. All
other registered users must be explicitly enrolled by an administrator. A
member can read published organization knowledge and suggest changes; only a
maintainer can publish or disable it. The maintainer role does not grant model
credential or account administration rights. A personal preference is visible
only to its owner. Turning personal Memory off stops new Agent proposals and
future injection, but manual editing remains available.

Manual saving in the browser is the user's confirmation. An Agent call to
`memory` or `knowledge` creates a durable proposal and returns
`pending_confirmation`. Only the owner or maintainer can confirm it through an
authenticated Web request. The tool capability inside OpenCode cannot call
that confirmation route. A pending update does not replace the active version.
Conflicts are rejected on confirmation and require reviewing the latest
version. Knowledge is deactivated rather than permanently deleted; inactive
items stay available in history and are omitted from new task recall.

## Materials and cases

The Knowledge page accepts DOCX, text PDF, Markdown, and TXT as source
materials. A saved upload does not create an active rule. Selecting "Start
extraction" queues a visible OpenCode conversation that reads the material and
submits sourced proposals. If no usable model is configured, the upload stays
saved for later extraction. A maintainer previews the proposed text and
selected excerpts before publication. The original document's access policy
is unchanged; published excerpts are stored with the knowledge version.

In a contract conversation, the user can mark a review, negotiation, or
disposition stage complete. This queues a case-drafting request. A review
finding or risk feedback is a record of that stage, not proof of formal
approval. The Agent must not invent an approver, approval rationale, or final
decision. Cases require at least one source excerpt. The source document ID,
hash, block ID, and exact excerpt are checked for Agent-submitted sources.

## Recall and migration

Personal active memories continue to use the existing per-turn snapshot and
their original IDs. Existing rows are migrated in place and retain their
enabled state and citation history. Organization rules are loaded in addition
to the selected personal risk scheme. If a rule's applicability metadata is
missing in the current contract, it stays visible with an explicit
"applicability unknown" flag. Templates and cases are retrieved on demand
with permission and active-state filtering, using exact filters and keyword
matching. No vector retrieval is implied.

When entering Knowledge from an active contract conversation, the "Current
contract applicability" form lets the owner confirm contract type, project,
department, and exact counterparty identity. Unknown values stay blank;
potentially applicable rules remain visible with an unknown-applicability flag.

Before deploying to an existing data directory, stop Web writes and back up
the whole directory (SQLite, files, and encryption keys). Update Web and the
bundled OpenCode plugin together, then restart idle runtimes. Former personal
risk schemes and public examples are not automatically promoted to organization
knowledge. The legacy memory DELETE endpoint returns 410; use disable and
restore in the Knowledge page. Old completed chats retain their historical
text and references. Revoked members cannot make new organization knowledge
queries or open organization evidence.
