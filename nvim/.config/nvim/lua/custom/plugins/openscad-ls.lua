-- lua/custom/plugins/openscad-ls.lua
-- In-process OpenSCAD language server: diagnostics, completion, hover,
-- goto-definition and formatting, implemented as a `vim.lsp.start` cmd
-- function rather than a child process.
--
-- Replaces the Mason-installed Rust `openscad_lsp`, which kept its own copy of
-- the document and, after an external reload, returned formatting edits
-- computed against stale text -- silently reverting files on save. This server
-- keeps no document state at all. See the project README for the details.
--
-- `build` compiles the tree-sitter OpenSCAD grammar into the plugin's own
-- `parser/` directory; nvim-treesitter's pinned master has no `openscad` entry,
-- so `:TSInstall openscad` will not provide it.
return {
  {
    'Turizmo/openscad-ls.nvim',
    build = './build.sh',
    ft = 'openscad',
    config = function()
      -- The diagnostics backend shells out to `openscad`, which needs this to
      -- find BOSL2. Matches the <leader>o preview keymap in init.lua.
      vim.env.OPENSCADPATH = vim.env.OPENSCADPATH or '/usr/share/openscad/libraries'
      require('openscad-ls').setup()
    end,
  },
}
