# Install and configuration
# Base install is Endeavour with i3 selected as window manager during install.

# Virtualbox guest config:
#sudo pacman -S virtualbox-guest-utils	# Install guest utilities
#sudo usermod -a -G vboxsf $USER		# Adds the current user to vboxsf group, this gives permisson to folders shared by the host.

# VMWARE guest config (xclip and gtkmm3 should also be installed on any machine)
sudo pacman -S open-vm-tools		# vmware tools
sudo pacman -S xclip			# clipboard manager for X11
sudo pacman -S gtkmm3			# GTK3

# Additional programs:
sudo pacman -S yazi			# terminal file manager
sudo pacman -S neovim			# text/code editor
sudo pacman -S ghostty			# terminal emulator
yay -S libreoffice-fresh		# open source office suite
yay -S openhantek6022			# oscilloscope software
yay -S obsidian				# note taking
yay -S orca-slicer-bin			# slicer for 3d printer
yay -S openscad-git			# 3d modeller
yay -S openscad-bosl2-git		# Openscad library
sudo pacman -S rust			# Dependency of openscad-lsp

# Addtional tools:
sudo pacman -S stow			# symlinking for dotfiles
sudo pacman -S zoxide			# easily find the most accessed files
sudo pacman -S lazygit			# terminal gui for git
sudo pacman -S qt5ct			# Allow to set a system wide theme for qt5
sudo pacman -S xdotool			# Automation tool
yay -S 7zip				# Compression tool


# Git config:
git config --global user.email "stianfoss.90+github@gmail.com"
git config --global user.name "Turizmo"

# Congifure SSH to push to github or pull private repositories:
ssh-keygen -t ed25519 -C "stianfoss.90+github@gmail.com"	# generate key
cat ~/.ssh/id_ed25519.pub					# fetch the public key
# then copy the the entire output from cat into github webpage:
# Sign in → Settings → SSH and GPG keys → New SSH key

# the first time git is used it needs to be in the teriminal and answer yes at the fingerprint.

# use stow to get and symlink dotfiles:
cd ~							# move to the user directory
git clone git@github.com:Turizmo/dotfiles.git 		# get dotfiles from git
mv ~/.bashrc ~/.bashrc.backup				# backup bashrc
mv ~/.config/i3/config ~/.config/i3/config.backup	# backup i3 config
cd dotfiles						# move to the dotfiles directory
stow -R */						# stow all dotfiles
