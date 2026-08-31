# Slash Command Removal Design

## Scope

Remove `/fork`, `/undo`, `/thinking`, `/btw`, `/goal`, and `/clear` from the
composer slash-command interface in the release branch.

The underlying capabilities remain available through their existing dedicated
UI controls. The BTW composer action uses a dedicated `openBtw` event instead of
an internal slash-command string.

## Behavior

- Removed commands are absent from the built-in slash menu.
- A hand-typed removed command is submitted as ordinary user text and cannot
  activate a session skill through the slash fallback.
- Existing commands such as `/new`, `/plan`, `/swarm`, `/compact`, `/export`,
  `/status`, and `/login` keep their current behavior.
- Removed command-only localization entries are deleted.

## Verification

Update slash-menu coverage for the removed names and run the frontend test,
typecheck, build, and diff checks before publishing the image.
