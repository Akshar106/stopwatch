# Restore drill

A quarterly rehearsal of [RB-7](RB-7-restore-database.md), so that the first real restore is not the first restore ([05 §10.5](../05-security-reliability.md#105-backups-and-disaster-recovery), [06 §11](../06-quality-operations.md#11-operating-cadence)). The drill restores into a throwaway Neon branch and **never switches production**.

**Targets:** RPO ≤ 24 h (nightly `pg_dump`), RTO < 1 h from "start" to "verified restored branch".

## Procedure

Allow about an hour. Record every timestamp in the log below as you go (UTC).

1. **Start the clock** (`t0`). Note the operator and the reason (scheduled quarterly drill).
2. **Pick the source.** Alternate between the two each quarter so both paths stay practiced:
   - *Dump drill:* the newest object in `s3://stopwatch-prod-lake/backups/postgres/`. Its date sets the achieved RPO (time between the dump and `t0`).
   - *PITR drill:* a Neon point-in-time branch of `main` at `t0 − 1 h` (if the free-plan history window allows it).
3. **Restore into a new branch** named `drill-YYYYMMDD`, following RB-7 Option A or B. Keep the dump in a new, empty directory outside the repository and delete it at the end.
4. **Verify** (RB-7 "Verify the branch"):
   - `alembic current` equals head.
   - Row counts for `users`, `saved_commutes`, `audit_log` are within the expected range of the last known values; `max(audit_log.at)` is close to the dump time.
   - A local API pointed at the branch (`DATABASE_URL` = branch app URL, `DATABASE_OWNER_URL` = branch owner URL) serves `GET /api/v1/healthz`, a demo sign-in, and listing a commute created during the drill.
   - Do **not** point `make test-integration` at a Neon branch. The suite (`backend/tests/conftest.py`) creates its own scratch database and, if missing, a `stopwatch_app` login role with the local-only password, so it tests the server rather than the restored data and can leave a weak role behind. [05 §10.5](../05-security-reliability.md#105-backups-and-disaster-recovery) says "run the integration suite against it"; until a read-only `make verify-db` exists ([06 §10](../06-quality-operations.md#10-incident-runbooks)), the checks above replace that step.
5. **Stop the clock** (`t1`) once verification passes. Achieved RTO = `t1 − t0`.
6. **Clean up:** delete the `drill-…` branch and the local dump file.
7. **Log** the row below, and open issues for anything that was slow, unclear or broken. Update RB-7 in the same PR if a step was wrong.

## What counts as a failed drill

- RTO over 1 h, or RPO over 24 h (for example, last night's backup was missing).
- Any manual step that was not in RB-7.
- Verification could not be completed.

A failed drill is useful: log it honestly and fix the gap before the next quarter.

## Log

| Date (UTC) | Operator | Source (dump date or PITR point) | Achieved RPO | Start (`t0`) | Verified (`t1`) | Achieved RTO | Verification (counts, API smoke) | Issues found / follow-ups |
|---|---|---|---|---|---|---|---|---|
| | | | | | | | | |
