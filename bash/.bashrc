#
# ~/.bashrc
#

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

alias ls='ls --color=auto'
alias grep='grep --color=auto'
PS1='[\u@\h \W]\$ '

# Set neovim as the default editor
export EDITOR=nvim
export VISUAL=nvim

# Set dark theme for QT apps
export QT_QPA_PLATFORMTHEME=qt5ct

# Make y a shorthand for yazi and make it possible to use yazi to navigate the directory of the terminal
function y() {
	local tmp="$(mktemp -t "yazi-cwd.XXXXXX")" cwd
	yazi "$@" --cwd-file="$tmp"
	IFS= read -r -d '' cwd < "$tmp"
	[ -n "$cwd" ] && [ "$cwd" != "$PWD" ] && builtin cd -- "$cwd"
	rm -f -- "$tmp"
}

# initialize zoxide
eval "$(zoxide init bash)"
