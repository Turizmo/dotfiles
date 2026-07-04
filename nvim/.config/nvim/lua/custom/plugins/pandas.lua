-- lua/custom/plugins/pandas.lua
-- Jupyter-kernel code execution with inline output (pandas DataFrames render
-- as text tables directly under the evaluated cell), plus .ipynb <-> .py sync.
--
-- Requires (install via pacman): python-pandas python-pynvim python-ipykernel
-- python-jupyter-client, and a registered kernel:
--   python3 -m ipykernel install --user --name python3 --display-name "Python 3"
--
-- Usage:
--   1. Open a .py file, split into cells with `# %%` comments.
--   2. <leader>mi to start a kernel (pick "python3").
--   3. <leader>mc runs the `# %%` block under the cursor (first run or re-run).
--      <leader>me / <leader>mv evaluate a motion/visual selection instead.
--   4. Output renders as virtual lines directly below the cell.
--
-- Note: MoltenReevaluateCell (Molten's own command) only works on a cell
-- that has *already* been evaluated once -- it errors "not in a cell"
-- otherwise. <leader>mc below finds the `# %%` block under the cursor and
-- runs MoltenEvaluateVisual on it instead, so it works the first time too.

-- Trim trailing blank lines so a cell's end boundary sits on the last real
-- line of code, not a separator blank line -- a cursor resting on that
-- blank line would otherwise fall just outside the registered span.
local function trim_trailing_blank(start, stop)
  while stop > start and vim.fn.getline(stop):match '^%s*$' do
    stop = stop - 1
  end
  return stop
end

-- Set the '< / '> marks directly (linewise, like a `V`-selection would)
-- instead of driving real Visual mode through :normal -- doing it via
-- :normal from a mapping callback left the marks unset and Molten errored
-- "No visual selection found".
local function evaluate_range(start, stop)
  vim.fn.setpos("'<", { 0, start, 1, 0 })
  vim.fn.setpos("'>", { 0, stop, 2147483647, 0 })
  vim.cmd 'MoltenEvaluateVisual'
end

local function molten_evaluate_cell()
  local start = vim.fn.search('^# %%', 'bcnW')
  if start == 0 then
    start = 1
  end
  local stop = vim.fn.search('^# %%', 'nW')
  stop = (stop == 0) and vim.fn.line '$' or (stop - 1)
  evaluate_range(start, trim_trailing_blank(start, stop))
end

-- Runs every `# %%` cell above the one under the cursor, in order, top to
-- bottom -- like Jupyter's "Run All Above". Cells are evaluated as
-- separate MoltenEvaluateVisual calls (not merged into one), same as
-- running <leader>mc on each individually, so they show up as their own
-- tracked cells with their own output. Kernels process execute_requests
-- in the order sent, so firing them off back-to-back without waiting for
-- each to finish is safe -- order is preserved.
local function molten_evaluate_above()
  local current_start = vim.fn.search('^# %%', 'bcnW')
  current_start = (current_start == 0) and vim.fn.line '.' or current_start

  local marker_lines = {}
  for lnum = 1, current_start - 1 do
    if vim.fn.getline(lnum):match '^# %%' then
      table.insert(marker_lines, lnum)
    end
  end

  if #marker_lines == 0 then
    vim.notify('[Molten] No cells above the cursor', vim.log.levels.INFO)
    return
  end

  for i, start in ipairs(marker_lines) do
    local stop = (marker_lines[i + 1] or current_start) - 1
    evaluate_range(start, trim_trailing_blank(start, stop))
  end
end

return {
  {
    'benlubas/molten-nvim',
    build = ':UpdateRemotePlugins',
    ft = { 'python', 'quarto', 'markdown' },
    init = function()
      -- No image.nvim: xfce4-terminal has no kitty-graphics/sixel support.
      -- Plots would need ueberzugpp; tables render fine as text either way.
      vim.g.molten_image_provider = 'none'
      vim.g.molten_auto_open_output = true
      vim.g.molten_output_virt_lines = true
      vim.g.molten_wrap_output = false -- no line-wrap; scroll sideways to see extra columns instead
      vim.g.molten_virt_text_output = false
      vim.g.molten_output_win_max_height = 20
      -- Default "open_then_enter" only *opens* the float on the first
      -- <leader>mo press and needs a second press to actually focus it.
      -- "open_and_enter" opens and focuses in one press.
      vim.g.molten_enter_output_behavior = 'open_and_enter'
    end,
    config = function()
      -- Molten gives its own :MoltenInfo window q/<Esc> to close, but not
      -- the regular output float you land in via <leader>mo -- there's no
      -- built-in single-key way out of it, so relying on a fresh <leader>
      -- combo right after the window-focus switch can be flaky. Give it
      -- the same q/<Esc>-closes convention as help/preview windows.
      vim.api.nvim_create_autocmd('FileType', {
        pattern = 'molten_output',
        callback = function(ev)
          local map_opts = { buffer = ev.buf, silent = true, nowait = true }
          vim.keymap.set('n', 'q', '<cmd>MoltenHideOutput<CR>', map_opts)
          vim.keymap.set('n', '<Esc>', '<cmd>MoltenHideOutput<CR>', map_opts)
          -- FileType fires before the floating window exists (Molten sets
          -- it on the buffer before calling open_win), so there's no
          -- window yet to set 'list'/'listchars' on. Wait for the buffer
          -- to actually appear in a window instead.
          vim.api.nvim_create_autocmd('BufWinEnter', {
            buffer = ev.buf,
            once = true,
            callback = function()
              -- With wrap off, mark when a line has more content
              -- off-screen so it's obvious there's more to scroll to
              -- (h/l, zl/zh, zL/zH all work normally in nowrap).
              vim.wo.list = true
              vim.wo.listchars = 'precedes:<,extends:>'
            end,
          })
        end,
      })
    end,
    keys = {
      { '<leader>mi', '<cmd>MoltenInit<CR>', desc = '[M]olten [I]nitialize kernel' },
      { '<leader>me', '<cmd>MoltenEvaluateOperator<CR>', desc = '[M]olten [E]valuate operator' },
      { '<leader>ml', '<cmd>MoltenEvaluateLine<CR>', desc = '[M]olten Evaluate [L]ine' },
      { '<leader>mc', molten_evaluate_cell, desc = '[M]olten Evaluate [C]ell (under cursor)' },
      { '<leader>ma', molten_evaluate_above, desc = '[M]olten Evaluate [A]bove (all cells before cursor)' },
      { '<leader>mv', ':<C-u>MoltenEvaluateVisual<CR>gv', mode = 'v', desc = '[M]olten Evaluate [V]isual' },
      { '<leader>mo', '<cmd>noautocmd MoltenEnterOutput<CR>', desc = '[M]olten [O]pen output window' },
      { '<leader>mh', '<cmd>MoltenHideOutput<CR>', desc = '[M]olten [H]ide output' },
      { '<leader>md', '<cmd>MoltenDelete<CR>', desc = '[M]olten [D]elete cell output' },
    },
  },
  { -- Edit .ipynb notebooks as plain Python, synced back to notebook JSON
    'GCBallesteros/jupytext.nvim',
    lazy = false,
    opts = {
      style = 'percent', -- pairs .ipynb with a plain .py using '# %%' cell markers
      output_extension = 'py',
      force_ft = 'python',
    },
  },
}
