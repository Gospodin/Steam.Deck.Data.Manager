#!/bin/bash
#Steam Deck Data Manager by Gospodin
#Source: https://github.com/Gospodin/Steam.Deck.Data.Manager

#stop running script if anything returns an error (non-zero exit )
set -e

repo_url="https://raw.githubusercontent.com/Gospodin/Steam.Deck.Data.Manager/master"

tmp_dir="/tmp/gospodin.SDDM.install"

script_install_dir="/home/deck/.local/share/Gospodin/SDDM"
script_file="data-manager.py" 

device_name="$(uname --nodename)"
user="$(id -u deck)"

if [ "$device_name" !='' "steamdeck" ] || [ "$user" != "1000" ]; then
  zenity --question --width=400 \
  --text="This code has been written specifically for the Steam Deck with user Deck \
  \nIt appears you are running on a different system/non-standard configuration. \
  \nAre you sure you want to continue?"
  if [ "$?" != 0 ]; then
    #NOTE: This code will never be reached due to "set -e", the system will already exit for us but just incase keep this
    echo "bye then! xxx"
    exit 1;
  fi
fi

function install_SDDM () {
  zenity --question --width=400 \
    --text="Read $repo_url/README.md before proceeding. \
    \nWould you like to add Shader Cache Killer to your Steam Library?"
  if [ "$?" != 0 ]; then
    #NOTE: This code will never be reached due to "set -e", the system will already exit for us but just incase keep this
    echo "bye then! xxx"
    exit 0;
  fi

  echo "Making tmp folder $tmp_dir"
  mkdir -p "$tmp_dir"

  echo "Making install folder $script_install_dir"
  mkdir -p "$script_install_dir"

  echo "Downloading Required Files"
  curl -o "$tmp_dir/$script_file" "$repo_url/$script_file"
  
  echo "Installing dependencies: during this process, Steam OS will exit read-only mode and then return to it once completed."
  sudo steamos-readonly disable
  sudo pacman -S python python-gobject gtk3 python-pygame
  sudo steamos-readonly enable

  echo "Copying $tmp_dir/$script_file to $script_install_dir/$script_file"
  sudo cp "$tmp_dir/$script_file" "$script_install_dir/$script_file"

  echo "Adding Execute and Removing Write Permissions"
  sudo chmod 555 "$script_install_dir/$script_file"

  add_killer="$(steamos-add-to-steam "$script_install_dir/$script_file")"

}

install_SDDM

echo "Done."