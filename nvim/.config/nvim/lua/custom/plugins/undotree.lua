-- lua/custom/plugins/undotree.lua
-- Visualize the undo history tree and switch between undo branches.
-- Pairs with `vim.o.undofile` (set in init.lua) so history persists across
-- sessions. Lazy-loads on the toggle key/command.
-- See https://github.com/mbbill/undotree
return {
  {
    'mbbill/undotree',
    cmd = { 'UndotreeToggle', 'UndotreeShow' },
    keys = {
      { '<leader>u', '<cmd>UndotreeToggle<cr>', desc = 'Toggle [U]ndotree' },
    },
    init = function()
      vim.g.undotree_WindowLayout = 2 -- tree left, diff bottom spanning full width
      vim.g.undotree_SetFocusWhenToggle = 1
    end,
  },
}
