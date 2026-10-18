# RB-7: Restore the Postgres database

**Use for:** data loss or corruption (bad migration, mistaken delete, compromised credentials), a missing nightly backup, and the quarterly [restore drill](restore-drill.md).
**Owner:** operator. **Related:** [05 §10.5](../05-security-reliability.md#105-backups-and-disaster-recovery), [06 §5](../06-quality-operations.md#5-database-migrations), [ADR-004](../adr/0004-neon-free-postgres-over-rds.md), [RB-6](RB-6-secret-leak.md).

Conventions are in the [runbooks README](README.md#conventions-used-in-the-runbooks).

## Symptoms

- Rows missing or wrong in user tables (users, sessions, saved commutes, alert rules) after a deploy, migration or manual action.
- A migration failed half-way in prod (the rehearsal on a Neon branch should catch this first).
- `maintenance` reports that last night's backup object `backups/postgres/{YYYY-MM-DD}.dump` is missing (two missing days is an incident).
- A credential compromise ([RB-6](RB-6-secret-leak.md)) where the attacker could have modified data.

## Impact

- User data only: accounts, saved commutes, alert rules, audit records, and the catalog/`route_daily_metrics` (both rebuildable from GTFS and the curated Parquet).
- Observations and published data are **not** in Postgres and are unaffected.
- Targets: **RPO ≤ 24 h** from the nightly dump (hours or less via Neon point-in-time restore within its window), **RTO < 1 h** ([05 §10.5](../05-security-reliability.md#105-backups-and-disaster-recovery)).

## Severity

SEV-2 if user data was lost or corrupted in prod. A drill is not an incident.

## Diagnose

1. **What broke, and when?** Pin the last known-good time from the deploy history, the audit log (`commute.delete`, `account.delete` bursts) or the migration log. That time is the restore point.
2. **Which source covers it?**
   - **Neon point-in-time restore** if the restore point is inside the plan's history window (short on the free plan; check the project settings).
   - Otherwise the **newest nightly dump before the restore point**:

     ```bash
     aws s3 ls s3://stopwatch-prod-lake/backups/postgres/ | tail -5
     ```

3. **Stop the bleeding first** if damage is ongoing: roll back the deploy (`make rollback FN=api ENV=prod`) or rotate the credential ([RB-6](RB-6-secret-leak.md)) before restoring, or the restored data will be damaged again.

## Mitigate (restore)

Always restore into a **new branch**, verify it, then switch. Never restore over `main` in place.

**Option A: Neon point-in-time restore**

1. Neon console → Branches → *Create branch* → parent `main`, *Past data* at the restore point; name it `restore-YYYYMMDD-HHMM`.
2. Copy the branch's connection strings for `stopwatch_owner` and `stopwatch_app`.

**Option B: nightly `pg_dump`**

1. Download the dump into a new empty directory outside the repository:

   ```bash
   mkdir -p ~/stopwatch-restore/$(date +%F) && cd ~/stopwatch-restore/$(date +%F)
   aws s3 cp s3://stopwatch-prod-lake/backups/postgres/2026-10-17.dump .
   ```

2. Create an empty branch for the restore (Neon console → *Create branch* → *Schema only* or an empty branch), named `restore-YYYYMMDD`.
3. Restore as the owner role:

   ```bash
   read -rs RESTORE_OWNER_URL
   pg_restore --no-owner --role=stopwatch_owner --exit-on-error -d "$RESTORE_OWNER_URL" 2026-10-17.dump
   ```

   Roles are cluster-level and are not in the dump, but every branch of the Neon project has the same roles, so the `GRANT`s in the dump (to `stopwatch_app_role`) restore cleanly. If they are missing, re-run the grant block from `backend/migrations/versions/0002_app_role_grants.py` by hand: `alembic upgrade head` is a no-op once `alembic_version` is already at head.

**Verify the branch before switching** (`make verify-db` is the planned target for this, [06 §10](../06-quality-operations.md#10-incident-runbooks); until it exists, run these checks):

```bash
cd backend && DATABASE_OWNER_URL="$RESTORE_OWNER_URL" uv run alembic current    # must equal head
psql "$RESTORE_OWNER_URL" -c "select count(*) from users;" \
                          -c "select count(*) from saved_commutes;" \
                          -c "select max(at) from audit_log;"                     # ≈ the restore point
```

Compare counts with the last known values (the drill log or yesterday's maintenance summary). Then point a local API at the branch and run a smoke test (demo sign-in, list commutes).

**Switch production to the restored branch**

1. Update `database_url` and `database_owner_url` in SSM with the branch's connection strings ([RB-6](RB-6-secret-leak.md) shows how to set a SecureString without shell history).
2. Force new containers: re-run the deploy workflow for the current commit (publishes new versions and moves `live`).
3. Keep the old `main` branch untouched until the incident is closed; it is the evidence. Rename branches in Neon afterwards if you want `main` to be the restored one.

## Verify

- `/api/v1/healthz` returns 200; demo sign-in, listing and saving a commute work.
- `alembic current` on the live database equals head.
- Spot-check a few known users' commute counts (with their consent if you contact them).
- The next nightly backup job succeeds against the new branch.

## Follow up

- Record the **RPO and RTO actually achieved** in the [drill log](restore-drill.md), even for a real incident.
- Users whose changes after the restore point were lost: tell them (the audit log identifies them pseudonymously by user ID).
- Postmortem for any real restore.
- Delete restore branches you no longer need (free-plan branch limits).
