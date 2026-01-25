# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a Kickstart.nvim-based Neovim configuration. Kickstart is a teaching-focused starting point, not a distribution. The configuration is primarily contained in a single `init.lua` file with modular plugin extensions.

## Structure

```
init.lua                    # Main configuration (~1000 lines)
lazy-lock.json              # Plugin version lockfile
lua/
  kickstart/
    health.lua              # :checkhealth implementation
    plugins/                # Optional kickstart plugins (debug, autopairs, gitsigns, etc.)
  custom/
    plugins/                # User customizations (flutter.lua, dart.lua)
```

## Key Commands

- `:Lazy` - Plugin manager UI (update, sync, health)
- `:Lazy update` - Update all plugins
- `:Mason` - LSP/tool installer UI
- `:checkhealth` - Verify Neovim requirements
- `<leader>o` - Open current file in OpenSCAD (custom binding)

## Plugin Management

Uses **lazy.nvim** for plugin management. Plugin specs are defined in `init.lua` with lazy-loading via:
- `event = 'VimEnter'` or `event = { 'BufReadPre', 'BufNewFile' }`
- `ft = { 'dart' }` for filetype-specific plugins
- `cmd = { 'LazyGit' }` for command-triggered loading
- `keys = { ... }` for keymap-triggered loading

Add custom plugins in `lua/custom/plugins/` to avoid merge conflicts with upstream kickstart.

## Code Style

Lua formatting via StyLua (`.stylua.toml`):
- 2-space indentation
- 160 column width
- Single quotes preferred
- No parentheses on single-argument calls

## Key Conventions

- **Leader key**: `<Space>`
- **Search mappings**: `<leader>s*` (files, grep, help, keymaps, diagnostics)
- **LSP mappings**: `gr*` (rename, references, definition, implementation)
- **Git hunk mappings**: `<leader>h*` (stage, reset, preview, blame)
- **Format**: `<leader>f`
- **Diagnostics quickfix**: `<leader>q`
- **Window navigation**: `<C-h/j/k/l>`

## LSP Configuration

Mason handles automatic LSP server installation. LSP attach behavior is defined in `init.lua` and reused via `require('kickstart.lsp')` for language-specific configs (e.g., Flutter).

## Custom Extensions

- **Flutter/Dart**: `lua/custom/plugins/flutter.lua` integrates flutter-tools.nvim with shared LSP keymaps
- **Obsidian**: Note-taking integration configured in main `init.lua`
- **AsyncRun**: Used for OpenSCAD integration
