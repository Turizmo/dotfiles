-- lua/custom/plugins/grug-far.lua
-- Project-wide find & replace in a live buffer, backed by ripgrep.
-- Type search + replace + optional file globs, see matches update live, then
-- apply across the project (or a single file / visual range). A saner
-- alternative to native `:%s` + `:cdo`.
-- Icons are optional (nvim-web-devicons / mini.icons); none installed here, so
-- it just renders without them.
-- See https://github.com/MagicDuck/grug-far.nvim
return {
  {
    'MagicDuck/grug-far.nvim',
    cmd = 'GrugFar',
    opts = {},
    keys = {
      {
        '<leader>sR',
        function()
          require('grug-far').open()
        end,
        desc = '[S]earch & [R]eplace (project)',
      },
      {
        '<leader>sR',
        function()
          -- Restrict the replace to the highlighted range.
          require('grug-far').open { visualSelectionUsage = 'operate-within-range' }
        end,
        mode = 'x',
        desc = '[S]earch & [R]eplace (selection)',
      },
      {
        '<leader>sc',
        function()
          -- Prefill paths to the current file only.
          require('grug-far').open { prefills = { paths = vim.fn.expand '%' } }
        end,
        desc = '[S]earch & replace [C]urrent file',
      },
    },
  },
}
