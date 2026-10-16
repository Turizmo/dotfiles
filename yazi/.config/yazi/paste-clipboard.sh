#!/usr/bin/env bash
# Paste files from the X clipboard into the current directory.
# Local files come as file:// URIs; VirtualBox shared-clipboard files come as
# http://localhost:PORT/vbcl/... URIs, which gio downloads like Thunar does.
set -u

uris=$(xclip -selection clipboard -o -t text/uri-list 2>/dev/null) || {
	echo "Clipboard holds no files" >&2
	exit 1
}

status=0
while IFS= read -r uri; do
	uri=${uri%$'\r'}
	[[ -z $uri || $uri == \#* ]] && continue
	if [[ $uri == file://* ]]; then
		path=$(python3 -c 'import sys, urllib.parse as u; print(u.unquote(sys.argv[1][7:]))' "$uri")
		cp -r -- "$path" . || status=1
	else
		gio copy -- "$uri" . || status=1
	fi
done <<<"$uris"
exit $status
