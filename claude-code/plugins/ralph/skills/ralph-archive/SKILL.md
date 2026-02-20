---
name: ralph-archive
description: Archive the current Ralph Loop and reset state files for the next loop
argument-hint: [--label archive-label]
allowed-tools: Bash(*)
---

# Ralph Archive — Archive Completed Loop

!`.ralph/scripts/ralph-archive.sh $ARGUMENTS`

## Result

The archive script above has been executed. Report the output to the user.

If the archive succeeded, tell the user:

- Their completed loop artifacts have been saved to `.ralph/archive/`
- The `.ralph/` state files have been reset with fresh templates
- They can start a new loop with `/ralph-init --name next-feature`

If the archive failed because state files were not found, tell the user there is nothing to archive — they may need to run `/ralph-init` first.
