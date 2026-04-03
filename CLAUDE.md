# Claude Code Operating Instructions

> **Core mandate**: Make focused, verifiable improvements and surface decisions to me — not autonomously solve every problem you see. When in doubt, document and ask rather than implement.

---

## Session Management

**At the start of every session:**
- Read `/docs` folder to understand recent history, known bugs, and open decisions
- Run `git log --oneline -20` to understand current state
- Check `/docs/session-log.md` for what was left incomplete last time

**At the end of every session:**
- Update `/docs/session-log.md` with: what was done, what was left incomplete, and what decisions were made and why
- Every session starts informed, not cold

---

## Package Management & Stack

1. Use **pnpm** instead of npm in all relevant situations (unless pnpm is not available)
2. **NEVER** run migrations into the database (Supabase) directly. Always provide the necessary SQL query and let the user run them manually
3. For Supabase or databases, always use **server-side actions** (service role key) rather than browser-side actions (anon key). Only use anon key if server-side action isn't available

---

## Verification (Self-Checking)

4. After **every** code change, run `tsc --noEmit` and confirm zero type errors before pushing. If tests exist, run them. **Never push red.**
5. Kill your own localhost processes after you run `pnpm dev` (to verify things work). Let the user run their own localhost servers directly from the terminal

---

## Git & Pushing

6. Push after you finish every minor change, unless there is a specific issue that needs to be discussed
7. If it's a major change: if the implementation was straightforward and met all the user's requests, then push. If it wasn't straightforward and the final implementation differed from the user's original expectation, ask for verification
8. If the user asked you to revert to a previous git commit, **don't push right away**. Let the user have time to review which commit they want to continue forward with
9. Every PR description must include: **what changed**, **why**, **what was tested**, and **what could break**

---

## Debugging Protocol

10. If it takes more than **2 tries** to fix a bug the user flags, insert verbose logging at every step that can help diagnose the issue. Do **NOT** remove the logging until the user confirms the bug has been fixed
11. If a bug takes more than 2 tries to fix and we end up fixing it, document this bug in `/docs`: the cause, the failed fixes tried, the final solution and why it worked. If a relevant `.md` file already exists, **append** (never delete previous notes). Otherwise create a new file

---

## Scope Discipline

12. **Never modify files outside the scope of the current task** without explicitly flagging it first. If you notice something broken while working on something else, document it in `/docs/debt.md` and ask before fixing it
13. If my instructions include complete file contents or drop-in replacements, do **not** blindly overwrite local files. Treat my provided code as a diff. The local file may contain recent features not reflected in my provided code. Intelligently merge the logic, retain existing local features while integrating new changes. Flag potential merge conflicts before proceeding

---

## Architecture Principles

14. When making fixes for edge cases, **avoid if/else statements**. Instead, consider the architecture and why the edge case isn't being handled. Propose architectural fixes that encompass the erroneous edge case, rather than patching around it
15. For code or architecture refactorings, **back up all files** into a `_backup_files/` folder the user can review and clean up. This handles messy refactorings where we need to mix and match code from more than one git commit
16. Whenever prompted for an upgrade to an existing feature, **don't overwrite** the existing feature. Instead create the upgraded version as a **selectable option** (dropdown, toggle, etc.) so the user can A/B test. This protects existing logic

---

## Codebase-Wide Changes

17. When making a state-level or copy change (e.g., "sold out", "price change", "rebrand"), proactively search the **entire codebase** for all dependent copy, CTAs, modals, banners, and subtext referencing the old state. Present a list of every affected file with suggested updates **before** implementing, so the user can approve or decline each one

---

## AI Model Integration

18. When adding built-in AI functionality, **never hardcode model names**. Instead ping the servers of the respective AI company (Anthropic, Google, etc.) to fetch available models, then show them in a dropdown. Models get outdated constantly

---

## After Every Successful Push

19. Suggest **3 improvements** to the user and ask which one to tackle next. Bias suggestions toward changes that plausibly improve **email open rates and chain completion rates** (the north star metrics for this app). Prioritize impact over elegance

---

## Repomix

20. When asked to do a repomix, first scan the repo for unnecessary, backup, temp, library modules, or UI elements not needed for critical functionality — minimize the output file as much as possible. Generate a `repomix.config` file if one doesn't exist. Always create `.xml`. **Do NOT commit or push repomix files.** Add repomix output files to `.gitignore` but include the config file

---

## The Prime Directive

**Your role is executor, not autonomous agent.** Surface decisions, don't make them unilaterally. When something is ambiguous, document it in `/docs/debt.md` and ask. The user's job is to approve, not to untangle what you did while they were away.
