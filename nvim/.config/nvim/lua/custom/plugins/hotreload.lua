-- lua/custom/plugins/hotreload.lua
-- Auto-reload buffers when files change on disk (e.g., edited by Claude Code).
-- Uses libuv fs_event watchers per visible buffer and runs `checktime` on
-- change, so edits from `claude` show up in real time without waiting for
-- focus/CursorHold. Only unmodified buffers are reloaded; a buffer with
-- unsaved edits is left alone -- Vim's built-in conflict prompt handles that
-- case, so init.lua deliberately defines no FileChangedShell handler.
-- Replaces the previous hand-rolled checktime/FileChangedShell autocmds.
-- See https://github.com/diogo464/hotreload.nvim
return {
  {
    'diogo464/hotreload.nvim',
    event = { 'BufReadPre', 'BufNewFile' },
    opts = {
      -- interval = nil -> fs_event watchers (no polling)
      -- Must stay false: silent = true runs `checktime` with
      -- `eventignore=FileChangedShell`, which swallows Vim's conflict prompt
      -- for a modified buffer whose file changed on disk.
      silent = false,
    },
  },
}
