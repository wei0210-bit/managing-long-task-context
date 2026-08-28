# <task-id>: <goal>

Updated: <UTC RFC3339 timestamp>
Phase: <current phase>

## Acceptance
- <current completion condition>

## Current State
- [STATE-01] <statement> | mutable: true | source: <stable source> | refreshed_at: <UTC RFC3339> | refresh_ref: <read-only observation>

## Decisions
- <decision> | why: <reason> | evidence: <stable reference>

## In Flight
<!-- If unused, In Flight is `- none`. -->
- [RUN-01] <action> | owner: <user/agent> | status: pending/blocked/unknown | started_at: <UTC RFC3339> | correlation_ref: <stable run locator> | recovery_ref: <read-only observation>

## Blockers
- none

## Next
1. First: <the one next action>

## Refresh On Resume
- STATE-01 -> <read-only refresh source>
- RUN-01 -> <read-only recovery source>
