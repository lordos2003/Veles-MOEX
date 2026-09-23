# OpenCode Task — Publish accepted MVP-6.4

## TASK_ID

PUBLISH-MASTER-AFTER-MVP-6.4

## STATUS

READY

## Context

MVP-6.4 has been independently accepted by ChatGPT.

Accepted review branch:

`agent/review/mvp-6.4`

Current verified review head:

`3ce159f4ac2b49088a53ce70cd0d24a3f5a5b684`

It is 4 commits ahead of the accepted published master:

`fe59bdf66c2401aadebd05562b1292e9cf73c287`

The four accepted MVP-6.4 commits are:

- `75e336fb651e6ebf79a4f55d18c76651f209c792`
- `63ca560954b5bbc2978f005b435929ab6eecabab`
- `b4a1deb5386eb9e2cbd3753f14eebac13deba0e7`
- `3ce159f4ac2b49088a53ce70cd0d24a3f5a5b684`

Do not change product code.

## Required action

Publish the already accepted MVP-6.4 changes to `origin/master`.

Use the existing local Git workflow.

First verify:

```powershell
git status
git fetch origin
git log --oneline --graph --decorate -12 master
git log --oneline --graph --decorate -12 origin/master
```

Then integrate the accepted review branch into local `master`.

Allowed:

- normal Git merge;
- fast-forward if Git determines that it is appropriate;
- push `master` to `origin`.

Forbidden:

- rebase;
- reset;
- force-push;
- squash;
- cherry-pick;
- modifying product files;
- resolving unexpected conflicts by inventing changes.

If `master` already contains the accepted commits, do not create duplicate commits. Verify and push only if needed.

If an unexpected divergence or conflict occurs, STOP before push and report the exact state.

## Required final verification

After successful integration:

```powershell
git fetch origin
git status
git log --oneline --graph --decorate -15 master
git log --oneline --graph --decorate -15 origin/master
git diff origin/master...master
```

Confirm:

1. `origin/master` contains all four accepted MVP-6.4 commits.
2. `origin/master` and local `master` point to the same commit.
3. Working tree is clean.
4. No product code was changed during publication.
5. No rebase, reset, squash, cherry-pick, or force-push was used.

## REPORT

After successful publication, create/update the publication report on `agent/control`.

Include:

- final `master` SHA;
- final `origin/master` SHA;
- merge/fast-forward result;
- push result;
- parent SHA(s), if a merge commit was created;
- `git status`;
- final `git log --oneline --graph --decorate -15`;
- confirmation that no product files were changed.

Do not modify `CHATGPT REVIEW`.

Stop after the REPORT.
