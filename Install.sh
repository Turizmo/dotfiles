# Install and configuration
# Base install is Endeavour with i3 selected as window manager during install.

# Additional programs:
sudo pacman -S yazi			# terminal file manager
sudo pacman -S neovim			# text/code editor
sudo pacman -S ghostty			# terminal emulator
yay -S libreoffice-fresh		# open source office suite
yay -S openhantek6022			# oscilloscope software
yay -S obsidian				# note taking
yay -S orca-slicer-bin			# slicer for 3d printer
yay -S openscad-git			# 3d modeller
sudo pacman -S rust			# Dependency of openscad-lsp

# Addtional tools:
sudo pacman -S stow			# symlinking for dotfiles
sudo pacman -S xclip			# clipboard manager for X11
sudo pacman -S zoxide			# easily find the most accessed files
sudo pacman -S lazygit			# terminal gui for git
sudo pacman -S qt5ct			# Allow to set a system wide theme for qt5

# Virtualbox guest config:
sudo pacman -S virtualbox-guest-utils	# Install guest utilities
sudo usermod -a -G vboxsf $USER		# Adds the current user to vboxsf group, this gives permisson to folders shared by the host.

# Git config:
git config --global user.email "stianfoss.90+github@gmail.com"
git config --global user.name "Turizmo"

# Congifure SSH to push to github:
ssh-keygen -t ed25519 -C "stianfoss.90+github@gmail.com"	# generate key
cat ~/.ssh/id_ed25519.pub					# fetch the public key
# then copy the the entire output from cat into github webpage:
# Sign in → Settings → SSH and GPG keys → New SSH key
