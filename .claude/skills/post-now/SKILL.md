---
name: post-now
description: |
  [OPS] Manually trigger the Meta auto-poster workflow on GitHub Actions,
  optionally as a dry run. Use when the user says "post now", "trigger
  the poster", "dry run the workflow", "test the pipeline", or
  "publish manually".
---

# Trigger the auto-poster

## When invoked

1. Ask: dry run, or actual post? Default to dry run for safety unless the
   user said "post for real" / "actually publish".
2. Use the GitHub MCP tool to dispatch the workflow:
   - Repo: `edagher92-coder/Claude-code-`
   - Workflow file: `auto-post.yml`
   - Ref: `claude/genre-content-page-anDnL` (or the current branch)
   - Inputs: `{ "dry_run": true | false }`
3. Provide the user with the Actions run URL so they can watch it.
4. If they ask for live updates, poll the run via `mcp__github__*` tools
   (do NOT use Bash `sleep`).

## Common scenarios

### "Check tonight's post will go through"
→ Dry run. Confirm the script picks up the right post id. Don't actually
post.

### "Post just Day 5 now"
→ The poster only posts items where `scheduledAtUtc` is within the last
60 min. If Day 5's scheduled time is in the future, the dry run will say
"0 due". Workaround: temporarily edit the post's `scheduledAtUtc` to a time
just past, push, run, then revert. Suggest this only if the user actually
wants to publish early.

### "The pipeline failed — debug it"
→ Fetch the failed run's logs via GitHub MCP. Common failure modes:
- Missing secrets → "[poster] Missing Meta credentials"
- Invalid token (401) → renew via `/meta-setup` Phase 2
- 400 image_url unreachable → image file missing from `automation/media/`
  or jsDelivr cache not yet populated (12 hr CDN cache)
- 400 aspect ratio → image not 4:5, 1:1, or 1.91:1

## When done

Report:
- Workflow run URL
- Status (dry-run / real, succeeded / failed)
- Post IDs that landed (or would have landed)
