#!/usr/bin/env bash
# Set up a fresh EndeavourOS install (i3 selected in the installer) like this machine.
#
# Fresh machine:
#   sudo pacman -S --needed git
#   git clone https://github.com/Turizmo/dotfiles.git ~/dotfiles
#   ~/dotfiles/install.sh
#
# Run single steps with:   ./install.sh <step> [<step>...]
# List the steps with:     ./install.sh help
# Every step is safe to run again.
#
# Manual work that stays manual:
#   - Log in to MEGAsync, then run `./install.sh repos` once ~/MEGA has synced.
#   - Home Assistant token: ~/.config/ha.env (chmod 600), see .bashrc.
set -euo pipefail

DOTFILES=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
GIT_EMAIL="stianfoss.90+github@gmail.com"
GIT_NAME="Turizmo"
GITHUB_USER="Turizmo"
BACKUP="$HOME/dotfiles-backup-$(date +%Y%m%d-%H%M%S)"

# Top level folders of the repo that are not stow packages
NOT_STOW=(packages system zram-bench zen)

STEPS=(packages vm flatpak pipx system git ssh claude stow zen services tailscale repos)

say() { printf '\n\e[1;34m==> %s\e[0m\n' "$*"; }
warn() { printf '\e[1;33m  ! %s\e[0m\n' "$*" >&2; }

# Package names from a list file, without comments and blank lines
read_list() { sed 's/#.*//' "$1" | xargs -r -n1; }

step_packages() {
	say "Official packages (packages/pacman.txt)"
	sudo pacman -Syu --needed --noconfirm $(read_list "$DOTFILES/packages/pacman.txt")

	say "AUR packages (packages/aur.txt)"
	command -v yay >/dev/null || { warn "yay missing; it ships with EndeavourOS"; return 1; }
	yay -S --needed --noconfirm --answerdiff None --answeredit None --answerclean None \
		$(read_list "$DOTFILES/packages/aur.txt")
}

# Guest tools for the hypervisor this runs in. Does nothing on real hardware.
step_vm() {
	local virt
	virt=$(systemd-detect-virt || true)
	case "$virt" in
	oracle)
		say "VirtualBox guest"
		sudo pacman -S --needed --noconfirm virtualbox-guest-utils
		sudo systemctl enable --now vboxservice.service
		# Access to folders shared by the host
		sudo usermod -aG vboxsf "$USER"
		# VirtualBox NAT drops/delays UDP, and Tailscale (WireGuard) is UDP: the exit
		# node is ~10x slower without this. Runs on the host with the VM off, so the
		# guest can only remind. Both were applied together; keep both.
		warn "On the host, with this VM powered off, tune the NAT network once:"
		warn "  VBoxManage modifyvm \"<VM name>\" --natsettings1 0,1024,1024,0,0"
		warn "  VBoxManage modifyvm \"<VM name>\" --nictype1 virtio"
		;;
	vmware)
		say "VMware guest"
		sudo pacman -S --needed --noconfirm open-vm-tools xf86-video-vmware gtkmm3
		sudo systemctl enable --now vmtoolsd.service vmware-vmblock-fuse.service
		;;
	*) say "No VM guest tools needed (virt: $virt)" ;;
	esac
}

step_flatpak() {
	say "Flatpak: OpenSCAD beta (user install)"
	flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
	flatpak remote-add --user --if-not-exists flathub-beta https://flathub.org/beta-repo/flathub-beta.flatpakrepo
	flatpak install --user -y --noninteractive flathub-beta org.openscad.OpenSCAD//beta
	# openscad-dark drives the docks over D-Bus (see OpenSCAD/.local/bin/openscad-dark)
	flatpak override --user --socket=session-bus --own-name=org.openscad.OpenSCAD org.openscad.OpenSCAD
}

step_pipx() {
	say "pipx / uv tools"
	pipx install qmk || true          # fails harmlessly if already installed
	uv python install 3.11 --preview || warn "uv python install failed" # python3.11 in ~/.local/bin
}

# Files under system/ are copied to the same path under /.
step_system() {
	say "System config (system/ -> /)"
	local src dst
	while IFS= read -r -d '' src; do
		dst="/${src#"$DOTFILES/system/"}"
		sudo install -Dm644 "$src" "$dst"
		echo "  $dst"
	done < <(find "$DOTFILES/system" -type f -print0)
	sudo udevadm control --reload-rules
	sudo sysctl --system >/dev/null

	# zram replaces zswap; zswap would sit in front of it and steal the pages
	if [[ -f /etc/default/grub ]]; then
		if ! grep -q 'zswap.enabled=0' /etc/default/grub; then
			sudo sed -i 's/^GRUB_CMDLINE_LINUX_DEFAULT="/&zswap.enabled=0 /' /etc/default/grub
			sudo grub-mkconfig -o /boot/grub/grub.cfg
		fi
	elif [[ -f /etc/kernel/cmdline ]]; then # systemd-boot
		if ! grep -q 'zswap.enabled=0' /etc/kernel/cmdline; then
			sudo sed -i '1s/$/ zswap.enabled=0/' /etc/kernel/cmdline
			sudo reinstall-kernels
		fi
	else
		warn "Unknown boot loader; add zswap.enabled=0 to the kernel command line by hand"
	fi

	# Serial ports (QMK flashing, oscilloscope)
	sudo usermod -aG uucp "$USER"
}

step_git() {
	say "Git identity"
	git config --global user.email "$GIT_EMAIL"
	git config --global user.name "$GIT_NAME"
}

# ssh -T always exits 1 on GitHub, so look at the greeting instead
github_ok() {
	local out
	out=$(ssh -T -o BatchMode=yes git@github.com 2>&1 || true)
	[[ $out == *"successfully authenticated"* ]]
}

step_ssh() {
	say "SSH key for GitHub"
	if [[ ! -f ~/.ssh/id_ed25519 ]]; then
		ssh-keygen -t ed25519 -C "$GIT_EMAIL" -f ~/.ssh/id_ed25519 -N ""
	fi
	# Trust github.com without the interactive fingerprint question
	ssh-keygen -F github.com >/dev/null 2>&1 ||
		ssh-keyscan -t ed25519 github.com >>~/.ssh/known_hosts 2>/dev/null

	if ! github_ok; then
		echo
		echo "Add this key on GitHub: Settings -> SSH and GPG keys -> New SSH key"
		echo "  https://github.com/settings/ssh/new"
		echo
		cat ~/.ssh/id_ed25519.pub
		echo
		read -rp "Press Enter when the key is added... "
		github_ok || { warn "GitHub still rejects the key"; return 1; }
	fi

	# The bootstrap clone uses https; push needs ssh
	git -C "$DOTFILES" remote set-url origin "git@github.com:$GITHUB_USER/dotfiles.git"
}

# Claude Code config and memory live in their own private repo (they hold
# private notes), cloned into claude/ which this repo ignores. claude-sync
# (in that repo) commits and pushes changes.
step_claude() {
	say "Claude config (private repo $GITHUB_USER/claude-config)"
	if [[ -d $DOTFILES/claude/.git ]]; then
		git -C "$DOTFILES/claude" pull -q --rebase
	else
		git clone "git@github.com:$GITHUB_USER/claude-config.git" "$DOTFILES/claude"
	fi
}

# Move a file that stow would collide with into $BACKUP.
backup_conflict() {
	local target=$1
	[[ -e $target || -L $target ]] || return 0
	# Already in the repo (itself a link, or under a linked folder): stow handles it
	[[ $(readlink -f "$target") == "$DOTFILES"/* ]] && return 0
	mkdir -p "$BACKUP/$(dirname "${target#"$HOME/"}")"
	mv "$target" "$BACKUP/${target#"$HOME/"}"
	echo "  backed up ~/${target#"$HOME/"}"
}

stow_packages() {
	local dir name skip
	shopt -s nullglob
	for dir in "$DOTFILES"/*/; do
		name=$(basename "$dir")
		skip=
		for s in "${NOT_STOW[@]}"; do [[ $name == "$s" ]] && skip=1; done
		[[ -n $skip ]] || echo "$name"
	done
}

step_stow() {
	say "Stow dotfiles into ~"
	local pkg file
	for pkg in $(stow_packages); do
		# Real files in the way (e.g. the installer's ~/.bashrc and ~/.config/i3/config)
		while IFS= read -r -d '' file; do
			backup_conflict "$HOME/${file#"$DOTFILES/$pkg/"}"
		done < <(find "$DOTFILES/$pkg" \( -type f -o -type l \) -print0)
		stow -d "$DOTFILES" -t "$HOME" -R "$pkg"
		echo "  $pkg"
	done
	[[ -d $BACKUP ]] && echo "Old files moved to $BACKUP"
	return 0
}

# The Zen profile folder has a random name per install, so stow can't place it.
# Link the repo's profile files into whatever the default profile is.
step_zen() {
	say "Zen browser profile"
	local ini="$HOME/.config/zen/profiles.ini" profile src
	if ! grep -qs '^Default=.*(release)' "$ini"; then
		echo "  Creating a profile (headless start)"
		timeout 15 zen-browser --headless >/dev/null 2>&1 || true
	fi
	profile=$(sed -n '/^\[Install/,/^\[/s/^Default=//p' "$ini" 2>/dev/null | head -1)
	[[ -n $profile ]] || { warn "No Zen profile found; start Zen once, then run: $0 zen"; return 0; }

	for src in "$DOTFILES"/zen/.config/zen/*/*; do
		local target="$HOME/.config/zen/$profile/$(basename "$src")"
		backup_conflict "$target"
		ln -sfn "$src" "$target"
		echo "  $target"
	done
}

step_services() {
	say "Services"
	sudo systemctl enable --now fstrim.timer
	systemctl --user daemon-reload
	systemctl --user enable --now ha-update-prompt.timer
	mkdir -p ~/ha-config # sshfs mount point for hamount
	mkdir -p ~/klipper-config # sshfs mount point for klmount
}

# Join the tailnet and send all traffic through the Pi (Home Assistant add-on,
# node "homeassistant"). Login is the Google account: `tailscale up` prints a URL
# to open, so no auth key is kept in the repo. `set` persists across reboots.
# No --accept-routes: the exit node already carries 10.0.0.0/24, so the
# "--accept-routes is false" health warning is expected.
step_tailscale() {
	say "Tailscale"
	sudo systemctl enable --now tailscaled
	if tailscale status >/dev/null 2>&1; then
		echo "  already logged in"
	else
		echo "  open the URL below and log in with Google"
		sudo tailscale up
	fi
	# allow-lan-access keeps the VirtualBox NAT network (10.0.2.0/24) reachable
	sudo tailscale set --exit-node=homeassistant --exit-node-allow-lan-access
}

# Clone every project repo that MEGA knows about but that is missing locally.
# Each ~/MEGA/Prosjekter/<Name>/!_GitInfo.txt holds the clone command.
step_repos() {
	say "Project repos from ~/MEGA/Prosjekter/*/!_GitInfo.txt"
	local info line args target
	shopt -s nullglob
	for info in "$HOME"/MEGA/Prosjekter/*/'!_GitInfo.txt'; do
		line=$(grep -m1 '^git clone ' "$info") || continue
		eval "args=($line)"
		target="$(dirname "$info")/${args[-1]}"
		if [[ -d $target/.git ]]; then
			echo "  ok      ${target#"$HOME/"}"
		else
			echo "  clone   ${target#"$HOME/"}"
			(cd "$(dirname "$info")" && "${args[@]}") || warn "clone failed: $info"
		fi
	done
	[[ -d $HOME/MEGA/Prosjekter ]] || warn "~/MEGA/Prosjekter not synced yet; log in to MEGAsync first"
}

# Not part of the full run: show where this machine and the package lists differ.
step_diff() {
	# The installer's own pacman runs (first lines of the log) are the EndeavourOS defaults
	local defaults
	defaults=$(grep -E "Running '(pacman -r /tmp/calamares|pacman --noconfirm -S |pacman -S --noconfirm --noprogressbar)" \
		/var/log/pacman.log | sed "s/.*Running '//;s/'$//" | xargs -n1 | grep -v '^-' | sort -u)
	say "Explicitly installed, not an EndeavourOS default, not in packages/*.txt"
	comm -23 <(pacman -Qqen | sort) <(sort -u <(echo "$defaults") <(read_list "$DOTFILES/packages/pacman.txt")) |
		sed 's/^/  pacman: /'
	comm -23 <(pacman -Qqem | sort) <(read_list "$DOTFILES/packages/aur.txt" | sort) | sed 's/^/  aur:    /'
	say "In packages/*.txt but not installed"
	comm -13 <(pacman -Qq | sort) <(cat <(read_list "$DOTFILES/packages/pacman.txt") \
		<(read_list "$DOTFILES/packages/aur.txt") | sort) | sed 's/^/  /'
}

usage() {
	echo "Usage: $0 [step...]"
	echo "No step runs all, in order: ${STEPS[*]}"
	echo "Extra step: diff (package lists vs. this machine)"
}

main() {
	[[ $EUID -ne 0 ]] || { echo "Run as your user, not root (sudo is used where needed)."; exit 1; }
	local steps=("$@")
	[[ ${#steps[@]} -gt 0 ]] || steps=("${STEPS[@]}")
	for s in "${steps[@]}"; do
		if [[ $s == help || $s == -h || $s == --help ]]; then usage; exit 0; fi
		declare -F "step_$s" >/dev/null || { usage; exit 1; }
	done
	for s in "${steps[@]}"; do "step_$s"; done
	if [[ $# -eq 0 ]]; then
		say "Done. Log out and back in (new groups, i3 config)."
		echo "Then: log in to MEGAsync, wait for sync, run: $0 repos"
	fi
}

main "$@"
