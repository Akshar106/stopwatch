## What and why

<!-- One or two sentences. Link the issue: "Closes #123". -->

## How it was tested

<!-- Commands run, tests added, screenshots for UI changes. -->

## Checklist

- [ ] Conventional-commit title (`feat:`, `fix:`, `docs:`, `chore:`, ...)
- [ ] Tests added or updated (unit / replay / integration / API / e2e as appropriate)
- [ ] Docs updated: `docs/contracts.md` if an interface changed, runbooks if operations changed
- [ ] ADR added or updated in `docs/adr/` for a significant design decision (or: not needed)

## Database migration?

- [ ] No schema change
- [ ] Yes: expand/contract compatible with the previous release, `downgrade` implemented and tested,
      `lock_timeout`/`statement_timeout` respected, long backfills moved to a job (docs/06 §5)

## Security and privacy impact

- [ ] None
- [ ] Touches authentication, sessions, CSRF or authorization (authorization matrix tests updated)
- [ ] Handles personal data (emails, commutes, push endpoints): retention, export and deletion considered;
      nothing personal is logged
- [ ] New external input (feed, user input, third-party API): validated, size/time-limited
- [ ] New secret or permission: stored in SSM, IAM least privilege, no secrets in code, logs or Terraform state
- [ ] New dependency: needed, maintained, license OK

## Cost impact

- [ ] None
- [ ] Adds or changes AWS resources: stays within the free tier / $1 budget (docs/04 §10.1), tagged
