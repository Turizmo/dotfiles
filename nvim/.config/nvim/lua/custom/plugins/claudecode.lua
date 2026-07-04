-- lua/custom/plugins/claudecode.lua
-- Claude Code IDE integration -- server only, no in-nvim terminal (no snacks).
-- The WebSocket server autostarts on launch (event = 'VeryLazy', auto_start)
-- and writes a lockfile to ~/.claude/ide/. Run `claude` in any terminal and
-- connect with `/ide`. Edits then arrive as native diffs against the live
-- buffer: accept with <leader>aa / :w, reject with <leader>ad / :q.
-- See https://github.com/coder/claudecode.nvim
return {
  {
    'coder/claudecode.nvim',
    event = 'VeryLazy',
    opts = {
      auto_start = true,
      terminal = { provider = 'none' },
    },
    keys = {
      { '<leader>a', nil, desc = 'AI/Claude Code' },
      { '<leader>ab', '<cmd>ClaudeCodeAdd %<cr>', desc = 'Add current buffer' },
      { '<leader>as', '<cmd>ClaudeCodeSend<cr>', mode = 'v', desc = 'Send to Claude' },
      {
        '<leader>as',
        '<cmd>ClaudeCodeTreeAdd<cr>',
        desc = 'Add file',
        ft = { 'NvimTree', 'neo-tree', 'oil', 'minifiles' },
      },
      -- Diff management
      { '<leader>aa', '<cmd>ClaudeCodeDiffAccept<cr>', desc = 'Accept diff' },
      { '<leader>ad', '<cmd>ClaudeCodeDiffDeny<cr>', desc = 'Deny diff' },
    },
  },
}
