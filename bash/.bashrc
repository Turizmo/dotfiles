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

# Aliases for streamlined system updates
update() {
  # System + AUR update; bail out if either fails so we don't clean a broken state
  sudo pacman -Syu --noconfirm || return
  yay -Syu --noconfirm || return

  # pacman's sandboxed downloader (alpm user) can leave behind stale download-*
  # temp directories. -Scc only removes files, so it errors on each one and exits
  # non-zero; clear them first so the cache clean runs without noise.
  sudo find /var/cache/pacman/pkg -maxdepth 1 -type d -name 'download-*' -exec rm -rf {} +

  # Trim caches without prompting, keeping the 2 newest versions of each package
  # so a bad update can still be rolled back: sudo pacman -U <cached .pkg>
  if command -v paccache >/dev/null 2>&1; then
    sudo paccache -rk2     # keep the 2 most recent versions of installed packages
    sudo paccache -ruk0    # remove every cached version of uninstalled packages
    # yay stores each AUR build in its own dir, so trim them one dir at a time
    find "${XDG_CACHE_HOME:-$HOME/.cache}/yay" -mindepth 1 -maxdepth 1 -type d \
      -exec paccache -rk2 -c {} \; 2>/dev/null
  else
    echo "update: pacman-contrib not installed; falling back to -Sc (no keep-2)." >&2
    echo "        install it with: sudo pacman -S pacman-contrib" >&2
    sudo pacman -Sc --noconfirm
    yay -Sc --noconfirm
  fi

  # Remove orphaned dependencies, if there are any
  local orphans
  orphans=$(pacman -Qtdq)
  if [[ -n "$orphans" ]]; then
    sudo pacman -Rns --noconfirm $orphans
  fi

  # Reboot if the kernel was updated. Arch/EndeavourOS doesn't create
  # /run/reboot-required, and kernel version strings (uname -r vs pacman -Q)
  # don't match, so instead check whether the running kernel's modules still
  # exist on disk -- a kernel update replaces that directory, so its absence
  # means the booted kernel is stale and a reboot is needed.
  if [[ ! -d "/usr/lib/modules/$(uname -r)" ]]; then
    echo "Kernel updated -- rebooting now..."
    sudo reboot
  fi
}
alias update-all='yay -Syu --noconfirm --answerdiff None --answeredit None --answerclean None --removemake'

# Path for firebase(flutter)
export PATH="$PATH":"$HOME/.pub-cache/bin"
export CHROME_EXECUTABLE=/usr/bin/chromium

# Android SDK
export ANDROID_HOME=/opt/android-sdk
export PATH=$PATH:$ANDROID_HOME/platform-tools:$ANDROID_HOME/cmdline-tools/latest/bin

# Created by `pipx` on 2026-05-05 12:51:29
export PATH="$PATH:/home/turizmo/.local/bin"
