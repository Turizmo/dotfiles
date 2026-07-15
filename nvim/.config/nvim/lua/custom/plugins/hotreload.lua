-- lua/custom/plugins/hotreload.lua
-- Auto-reload buffers when files change on disk (e.g., edited by Claude Code).
-- Uses libuv fs_event watchers per visible buffer and runs `checktime` on
-- change, so edits from `claude` show up in real time without waiting for
-- focus/CursorHold. Only unmodified buffers are reloaded; a buffer with
-- unsaved edits is left alone. In that conflict case the `FileChangedShell`
-- guard in init.lua prompts instead of letting a later `:w` silently
-- overwrite the external change.
-- Replaces the previous hand-rolled checktime/FileChangedShell autocmds.
-- See https://github.com/diogo464/hotreload.nvim
return {
  {
    'diogo464/hotreload.nvim',
    event = { 'BufReadPre', 'BufNewFile' },
    opts = {
      -- interval = nil -> fs_event watchers (no polling)
      silent = false, -- notify when a buffer is reloaded from disk
    },
  },
}
