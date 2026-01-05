-- lua/custom/plugins/flutter.lua
return {
  {
    'nvim-flutter/flutter-tools.nvim',
    lazy = false,
    dependencies = {
      'nvim-lua/plenary.nvim',
      'neovim/nvim-lspconfig',
    },
    config = function()
      require('flutter-tools').setup {
        widget_guides = { enabled = true },
        closing_tags = { highlight = 'Comment' },
        dev_log = { enabled = true, open_cmd = 'tabedit' },
        lsp = {
          on_attach = function(client, bufnr)
            local ok, ks = pcall(require, 'kickstart.lsp')
            if ok then
              ks.on_attach(client, bufnr)
            end
          end,
          -- no cmp_nvim_lsp here, blink.cmp handles completion
        },
      }
    end,
  },
}
