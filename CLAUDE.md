# Claude Guidelines — MidiTrain-5

## Package Manager
- Use **pnpm** instead of npm in all relevant situations (unless pnpm is not available)

---

## Git & Pushing
- Push after every minor change, unless there is a specific issue to discuss
- For major changes: push if implementation was straightforward and met the request; if it differed from expectation, ask for verification first
- If the user asked to revert to a previous commit, don't push right away — let them review which commit to continue from
- After a successful change or fix and push, **suggest 3 improvements** and ask which to tackle next

---

## Database (Supabase)
- Never run migrations directly — always provide the SQL and let the user run manually
- Always use server-side actions (service role key); only use anon key if server-side isn't available

---

## Debugging & Bug Fixes
- If a bug takes more than 2 tries to fix, insert **verbose logging at every step** — do not remove until user confirms it's fixed
- If a bug takes more than 2 tries and is eventually fixed, document it in `/docs`:
  - Include: bug description, cause, failed fixes tried, final solution and why it worked
  - If a similar bug doc exists, append to it (never delete previous notes); otherwise create a new file
- When fixing edge cases, avoid `if/else` patches — instead diagnose the architectural reason the case isn't handled and propose a structural fix

---

## Code Changes & Merging
- If user provides complete file contents or drop-in replacements, treat them as a **diff** — do not blindly overwrite
  - Retain existing local features; intelligently merge new logic; flag conflicts before proceeding
- For **state/copy changes** (e.g. "sold out", price change, rebrand): scan the entire codebase for all dependent copy, CTAs, modals, banners, and subtext referencing the old state — present a full list with suggested updates for approval before implementing

---

## Refactoring
- Back up all affected files into a `_backup_files/` folder before refactoring (extra layer of version control beyond git, for messy refactors that mix code from multiple commits)

---

## Feature Upgrades
- When upgrading an existing feature, **create the upgraded version as a new selectable option** in a dropdown rather than overwriting — allows A/B testing and avoids clobbering existing logic

---

## AI / Model Integration
- Never hardcode model names — ping the AI provider's servers to fetch available models and show them in a dropdown (models get outdated frequently)

---

## Repomix
- Before running repomix, scan the repo for unnecessary/backup/temp/library files not critical to functionality — minimize output size
- Generate a reusable `repomix.config` file if one doesn't exist; always output `.xml`
- Do **not** commit or push repomix output; add repomix output files to `.gitignore` (but keep the config file tracked)

---

## Localhost
- Kill your own localhost processes after running `pnpm dev` to verify things work — let the user run their own servers from the terminal
