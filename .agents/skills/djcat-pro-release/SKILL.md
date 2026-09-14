---
name: djcat-pro-release
description: Release or explicitly republish a DJCat Pro 5 version from bilixuesheng/DJCat-Pro-5. Use when the user asks to 发版、发布版本、紧急发布、重发版本、生成正式更新日志，或检查一次 DJCat Pro 发版是否完整。
---

# DJCat Pro 5 Release

Release DJCat Pro 5 from `main` with one internally consistent source commit, verified Windows artifacts, and a Ghost Downloader-style GitHub release.

## Required input

Resolve these before changing files:

- Target version, without guessing.
- Whether this is a new version or an explicit republish of an existing tag.
- A broad release category inferred from the verified change set, such as `功能更新`、`稳定更新`、`性能更新`、`体验更新` or `体验与稳定更新`.

If the version, release mode, or category is materially ambiguous, stop and ask. Do not infer a destructive republish from words such as “修一下” or “重新跑”。

## Release invariants

- Work on `bilixuesheng/DJCat-Pro-5` and finish on `main`.
- Preserve unrelated user changes. Never clean, reset, or overwrite them.
- Read `CONTEXT.md` before deciding what changed and use its project vocabulary.
- Build the release note from the commits and diffs since the previous release tag. Do not invent changes from chat history.
- Keep all release-owned changes in one atomic commit and push once. A partial version bump can trigger the release workflow with inconsistent inputs.
- Do not manually create a tag or GitHub Release for a normal release. `.github/workflows/main.yml` owns testing, packaging, tagging, and publication.
- Only republish when the user explicitly requests it. The workflow recognizes the exact commit subject `release: republish v<version>`.
- Current release artifacts are Windows x86_64 only: installer, installer SHA-256 file, and portable ZIP.
- Release notes contain no HTML comments or hidden metadata.
- The GitHub Release title is `v<version> · <broad category>`.
- The first release-note heading is `## [<version>] - YYYY-MM-DD - <broad category>`.
- The broad category must not name one concrete feature.
- Do not claim success before the release workflow and published artifacts are verified.

## Procedure

### 1. Inspect the release boundary

1. Confirm the current branch is `main`, fetch `origin/main` and tags, and inspect worktree status.
2. Identify the previous published tag.
3. Review `git log <previous-tag>..HEAD` and the corresponding diff.
4. Separate user-visible changes from tests, documentation, release bookkeeping, and reverted work.
5. Read the current version from all release-owned sources:
   - `app/common/config.py`
   - `pyproject.toml`
   - the editable project entry in `uv.lock`
6. Inspect `.github/workflows/main.yml` and the previous release note. Treat them as implementation evidence, not as permission to copy stale wording.

### 2. Choose the release category

Choose the narrowest truthful broad category:

| Change set | Category |
| --- | --- |
| Primarily new user-visible capability | 功能更新 |
| Primarily fixes and reliability | 稳定更新 |
| Primarily startup, memory, rendering, or responsiveness work | 性能更新 |
| Primarily interaction and presentation refinements | 体验更新 |
| Meaningful interaction refinements plus reliability fixes | 体验与稳定更新 |

If two categories remain equally plausible, ask the user. Never use a concrete title such as “定时任务更新”。

### 3. Remove the release-note comment dependency

The current workflow may still obtain the release title from an HTML metadata comment. On the first release that uses this skill:

1. Update `.github/workflows/main.yml` in the same atomic commit as the new version.
2. Parse the first release-note H2 with this semantic shape:

   `## [version] - YYYY-MM-DD - category`

3. Require the heading version to equal the tag version.
4. Produce `v<version> · <category>` as the workflow release title.
5. Fail with a clear error when the heading is missing or inconsistent; do not silently fall back to a title without the category.
6. Remove only the workflow's dependency on hidden metadata. Preserve its existing test, x86_64 build, checksum, prerelease, and explicit-republish behavior.

Do not migrate the workflow in a standalone push while the current tag already exists. Its path triggers the release workflow; bundle the migration with the next new-version release commit.

### 4. Update version sources

1. Update `VERSION` in `app/common/config.py`.
2. Update `[project].version` in `pyproject.toml`.
3. Run `uv lock` so the editable package version in `uv.lock` is generated rather than hand-maintained.
4. Search the release-owned files for the old version and confirm only intentional historical references remain.
5. Confirm all three active version sources are exactly equal.

If `uv lock` cannot complete, stop and report the blocker. Do not hand-edit generated dependency metadata merely to make the diff look complete.

### 5. Write the release note

Create `.github/release-notes/v<version>.md` with this shape:

```markdown
## [<version>] - YYYY-MM-DD - <broad category>

> [!IMPORTANT]
> One or two concise lines describing the release's user-visible theme.
> State that this release provides Windows x86_64 installer and portable builds.

### 功能更新 ✨

- Verified user-visible change By @contributor

### 功能优化 🔧

- Verified refinement By @contributor

### 问题修复 🐛

- Verified fix By @contributor

---

### 下载

**🪟 Windows**

- [x86_64 安装程序](https://github.com/bilixuesheng/DJCat-Pro-5/releases/download/v<version>/DJCat-Pro-v<version>-Windows-x86_64-Setup.exe) · [SHA-256](https://github.com/bilixuesheng/DJCat-Pro-5/releases/download/v<version>/DJCat-Pro-v<version>-Windows-x86_64-Setup.exe.sha256)
- [x86_64 便携版（ZIP）](https://github.com/bilixuesheng/DJCat-Pro-5/releases/download/v<version>/DJCat-Pro-v<version>-Windows-x86_64.zip)

---

**Full Changelog**: [v<previous>...v<version>](https://github.com/bilixuesheng/DJCat-Pro-5/compare/v<previous>...v<version>)

### Contributors

- @contributor
```

Apply these writing rules:

- Omit empty change sections.
- Group by user impact, not by commit count.
- Merge several implementation commits into one clear bullet when they deliver one behavior.
- Exclude release-lock repairs, mechanical version bumps, test-only changes, documentation-only changes, and fully reverted attempts unless users are affected.
- Attribute only contributors supported by the commit range.
- Keep product wording consistent with `CONTEXT.md`.
- Do not add HTML comments anywhere in the file.
- Do not include unverifiable performance, compatibility, or bug-fix claims.
- Preserve the Ghost Downloader-style hierarchy, callout, emoji section labels, downloads, full changelog, and contributors.

### 6. Validate before pushing

Run the strongest relevant local checks available:

```bash
uv sync --frozen
uv run --frozen python -m pytest -q
uv run --frozen python -m compileall -q app server tests
node --check server/static/admin.js
git diff --check
```

Also verify:

- All active version sources match the target version.
- The release-note path matches `v<version>.md`.
- The H2 version, date, and category are correct.
- The note has no HTML comments.
- Every download URL and comparison URL uses the target version.
- The workflow derives the categorized release title from the H2 and no longer depends on hidden metadata.
- The workflow still expects exactly three x86_64 release assets.
- Existing tests were not weakened or skipped to make the release pass.

State exactly which checks ran. If a platform-specific behavior was not tested on Windows hardware, say so; do not substitute “应该没问题”。

### 7. Commit and push atomically

Stage only the reviewed release files and any intentional `CONTEXT.md` update.

For a new version, use:

```text
release: 发布 v<version> <broad category>
```

For an explicitly authorized republish, use exactly:

```text
release: republish v<version>
```

Before pushing, inspect the staged diff and confirm it contains the complete version bump, lock update, release note, and one-time workflow migration when needed. Push the single commit to `origin/main`.

### 8. Verify publication

Monitor the triggered GitHub Actions run through completion. Confirm:

- Windows tests passed.
- The x86_64 standalone build, PE architecture check, ZIP, installer, and SHA-256 validation passed.
- The tag targets the intended release commit.
- The GitHub Release title is exactly `v<version> · <broad category>`.
- The published body starts with the required H2 and contains no HTML comments.
- Prerelease versions are marked as prereleases.
- Exactly these assets exist and are non-empty:
  - `DJCat-Pro-v<version>-Windows-x86_64-Setup.exe`
  - `DJCat-Pro-v<version>-Windows-x86_64-Setup.exe.sha256`
  - `DJCat-Pro-v<version>-Windows-x86_64.zip`
- The published installer hash matches the checksum file.

A normal “发布” also means completing the project's existing Client Update delivery route after the GitHub Release is healthy. Use only already configured repository or environment tooling to synchronize the installer to the fixed `DOWNLOAD_URL` object and update the existing update API metadata. If that route or its credentials are unavailable, report the exact blocker and do not claim the client rollout is complete.

### 9. Review project context

After the release, decide whether `CONTEXT.md` lacks a durable domain rule, ownership boundary, platform constraint, or operational invariant introduced by the release.

- Update it when the release changed such a durable fact.
- Do not add a chronological changelog or duplicate the release note.
- The skill itself and ordinary release bookkeeping do not require a `CONTEXT.md` change.

Finish with the release commit SHA, workflow result, release URL, verified asset list, tests run, Client Update delivery status, and whether `CONTEXT.md` changed.
