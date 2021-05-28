RELEASE_TYPE: patch

This release fixes #15, an issue introduced by 595f189 causing pollers to
perform slower because the event registration was not always reflecting the
connection state.
