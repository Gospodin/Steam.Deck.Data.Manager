#!/bin/python
import os
import shutil
import re
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, GdkPixbuf, Pango
import pygame
from pathlib import Path

LIBRARY_FOLDERS_VDF = Path("/home/deck/.local/share/Steam/steamapps/libraryfolders.vdf")
COMPATDATA_PATH = Path("/home/deck/.steam/steam/steamapps/compatdata")

def get_steam_library_paths():
    if not LIBRARY_FOLDERS_VDF.exists():
        return []
    with LIBRARY_FOLDERS_VDF.open("r") as f:
        content = f.read()
    paths = re.findall(r'"path"\s*"([^"]+)"', content)
    external_paths = [Path(p) / "steamapps" for p in paths if not p.startswith("/home/deck/.local/share/Steam")]
    return [p for p in external_paths if p.exists()]

MICROSD_PATHS = get_steam_library_paths()
MICROSD_PATH = MICROSD_PATHS[0] if MICROSD_PATHS else None
TARGET_DIR = MICROSD_PATH / "compatdata" if MICROSD_PATH else None

def get_game_name(appid):
    try:
        for lib_path in get_steam_library_paths() + [Path("/home/deck/.local/share/Steam/steamapps")]:
            acf_path = lib_path / f"appmanifest_{appid}.acf"
            if acf_path.exists():
                with acf_path.open("r") as f:
                    for line in f:
                        if '"name"' in line:
                            return line.split('"')[3].strip()
        if LIBRARY_FOLDERS_VDF.exists():
            with LIBRARY_FOLDERS_VDF.open("r") as f:
                content = f.read()
                match = re.search(rf'"{appid}"\s*{{[^}}]*"name"\s*"([^"]+)"', content, re.DOTALL)
                if match:
                    return match.group(1)
        return "Unknown Game"
    except Exception:
        return "Unknown Game"

def get_folder_size(path):
    total_size = 0
    for dirpath, _, filenames in os.walk(path, followlinks=False):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if os.path.islink(fp) and not os.path.exists(fp):
                continue
            try:
                total_size += os.path.getsize(fp)
            except (FileNotFoundError, PermissionError, OSError):
                continue
    return total_size / (1024 * 1024)

def get_game_icon(appid):
    base_path = Path(f"/home/deck/.steam/steam/appcache/librarycache/{appid}")
    preferred_files = ["header.jpg", "logo.png", "library_header.png"]
    
    for filename in preferred_files:
        icon_path = base_path / filename
        if icon_path.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(icon_path), -1, 128, True)
                return pixbuf
            except Exception:
                pass

    if base_path.exists():
        for file in base_path.iterdir():
            if file.is_file() and file.suffix.lower() in [".jpg", ".png"]:
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(file), -1, 128, True)
                    return pixbuf
                except Exception:
                    pass
    
    return None

def is_symlink(path):
    return os.path.islink(path)

def get_storage_location(path):
    if is_symlink(path):
        return f"microSD ({os.readlink(path)})"
    return f"Internal ({path})"

def toggle_symlink(appid_path, target_path):
    if not target_path:
        raise Exception("No SD card detected!")
    if is_symlink(appid_path):
        link_target = Path(os.readlink(appid_path))
        os.unlink(appid_path)
        if link_target.exists():
            shutil.move(link_target, appid_path)
        return "Moved back to internal storage"
    else:
        if not target_path.parent.exists():
            target_path.parent.mkdir(parents=True)
        shutil.move(appid_path, target_path)
        os.symlink(target_path, appid_path)
        return "Moved to microSD with symlink"

def get_valid_app_folders():
    app_folders = {}
    all_libs = get_steam_library_paths() + [Path("/home/deck/.local/share/Steam/steamapps")]
    installed_apps = set()
    for lib_path in all_libs:
        for acf in lib_path.glob("appmanifest_*.acf"):
            appid = acf.stem.split("_")[1]
            installed_apps.add(appid)
    for folder in COMPATDATA_PATH.iterdir():
        if folder.is_dir() and folder.name in installed_apps:
            appid = folder.name
            if appid not in app_folders:
                app_folders[appid] = folder
    return app_folders

class ProtonManagerWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title="Proton Prefix Manager")
        self.set_default_size(800, 400)

        pygame.init()
        pygame.joystick.init()
        self.joystick = None
        if pygame.joystick.get_count() > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            print(f"Joystick detected: {self.joystick.get_name()}")

        if not COMPATDATA_PATH.exists():
            self.show_error("compatdata folder not found!")
            return
        if not MICROSD_PATH:
            self.show_error("No SD card detected in Steam library!")
            return

        self.app_folders = get_valid_app_folders()
        if not self.app_folders:
            self.show_error("No valid Proton prefixes found in compatdata!")
            return

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        label = Gtk.Label(label=f"Using SD card: {MICROSD_PATH}")
        vbox.pack_start(label, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress_label = Gtk.Label(label="Loading games...")
        vbox.pack_start(self.progress_label, False, False, 0)
        vbox.pack_start(self.progress, False, False, 0)

        self.store = Gtk.ListStore(bool, str, str, float, bool, GdkPixbuf.Pixbuf)
        self.treeview = Gtk.TreeView(model=self.store)
        
        renderer_icon = Gtk.CellRendererPixbuf()
        column_icon = Gtk.TreeViewColumn("Icon", renderer_icon, pixbuf=5)
        column_icon.set_fixed_width(300)
        self.treeview.append_column(column_icon)

        renderer_toggle = Gtk.CellRendererToggle()
        renderer_toggle.connect("toggled", self.on_toggle_selection)
        column_toggle = Gtk.TreeViewColumn("Select", renderer_toggle, active=0)
        self.treeview.append_column(column_toggle)

        columns = ["AppID", "Game Name", "Size (MB)", "Location"]
        for i, column_title in enumerate(columns):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(column_title, renderer, text=i + 1)
            column.set_sort_column_id(i + 1)
            if column_title == "AppID":
                self.store.set_sort_func(1, self.string_sort_func, 1)
            elif column_title == "Game Name":
                self.store.set_sort_func(2, self.string_sort_func, 2)
            elif column_title == "Size (MB)":
                renderer.set_property("xalign", 1.0)
                column.set_cell_data_func(renderer, lambda col, cell, model, iter, data: cell.set_property("text", f"{model[iter][3]:.2f}"))
                self.store.set_sort_func(3, self.size_sort_func, 3)
                column.set_sort_order(Gtk.SortType.DESCENDING)
            elif column_title == "Location":
                renderer.set_property("wrap-width", 200)
                renderer.set_property("wrap-mode", Pango.WrapMode.WORD)
                column.set_cell_data_func(renderer, lambda col, cell, model, iter, data: cell.set_property("text", get_storage_location(COMPATDATA_PATH / model[iter][1])))
                self.store.set_sort_func(4, self.string_sort_func, 4)
            self.treeview.append_column(column)

        self.treeview.connect("row-activated", self.on_row_activated)
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.add(self.treeview)
        vbox.pack_start(scrolled_window, True, True, 0)

        toggle_button = Gtk.Button(label="Toggle Selected Locations")
        toggle_button.connect("clicked", self.on_toggle_clicked)
        vbox.pack_start(toggle_button, False, False, 0)

        # Изначально список пустой, начинаем асинхронное заполнение
        self.treeview.set_cursor(Gtk.TreePath.new_first())
        self.treeview.get_column(3).clicked()  # Активируем сортировку по "Size (MB)"
        GLib.timeout_add(50, self.handle_gamepad)
        GLib.timeout_add(100, self.populate_store_async)

    def string_sort_func(self, model, iter1, iter2, column_idx):
        val1 = model[iter1][column_idx]
        val2 = model[iter2][column_idx]
        if column_idx == 4:
            val1 = get_storage_location(COMPATDATA_PATH / model[iter1][1])
            val2 = get_storage_location(COMPATDATA_PATH / model[iter2][1])
        return -1 if val1 > val2 else (1 if val1 < val2 else 0)

    def size_sort_func(self, model, iter1, iter2, column_idx):
        size1 = model[iter1][column_idx]
        size2 = model[iter2][column_idx]
        return -1 if size1 > size2 else (1 if size1 < size2 else 0)

    def populate_store_async(self):
        total_folders = len(self.app_folders)
        seen_appids = set()

        def process_next_game(index):
            if index >= len(self.app_folders):
                GLib.idle_add(self.progress.set_fraction, 1.0)
                GLib.idle_add(self.progress_label.set_text, "Loading complete")
                GLib.timeout_add(500, lambda: self.progress.hide() or self.progress_label.hide())
                return False

            appid, folder = list(self.app_folders.items())[index]
            if appid in seen_appids:
                GLib.timeout_add(50, process_next_game, index + 1)
                return False

            name = get_game_name(appid)
            GLib.idle_add(self.progress_label.set_text, f"Loading: {name}")
            size = get_folder_size(folder)
            symlink = is_symlink(folder)
            icon = get_game_icon(appid)
            GLib.idle_add(self.add_to_store, (False, appid, name, size, symlink, icon))
            seen_appids.add(appid)
            fraction = (index + 1) / total_folders
            GLib.idle_add(self.progress.set_fraction, fraction)

            GLib.timeout_add(50, process_next_game, index + 1)
            return False

        GLib.timeout_add(50, process_next_game, 0)
        return False

    def add_to_store(self, data):
        selected, appid, name, size, symlink, icon = data
        self.store.append([selected, appid, name, size, symlink, icon])
        return False

    def on_toggle_selection(self, widget, path):
        self.store[path][0] = not self.store[path][0]

    def on_row_activated(self, treeview, path, column):
        model = treeview.get_model()
        treeiter = model.get_iter(path)
        if treeiter:
            self.toggle_location([treeiter])

    def show_error(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self, flags=0, message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK, text=message
        )
        dialog.run()
        dialog.destroy()
        Gtk.main_quit()

    def on_toggle_clicked(self, button):
        selected_rows = [self.store.get_iter(row.path) for row in self.store if row[0]]
        if not selected_rows:
            selection = self.treeview.get_selection()
            model, treeiter = selection.get_selected()
            if treeiter:
                self.toggle_location([treeiter])
        else:
            self.toggle_location(selected_rows)

    def toggle_location(self, treeiters):
        actions = []
        for treeiter in treeiters:
            appid = self.store[treeiter][1]
            selected_folder = COMPATDATA_PATH / appid
            action = "Move to microSD" if not self.store[treeiter][4] else "Move back to internal storage"
            game_name = self.store[treeiter][2]
            actions.append((treeiter, appid, selected_folder, TARGET_DIR / appid, action, game_name))

        if not actions:
            return

        message = "Are you sure you want to perform the following actions?\n\n"
        for _, appid, _, _, action, game_name in actions:
            message += f"{game_name} ({appid}): {action}\n"

        dialog = Gtk.MessageDialog(
            transient_for=self, flags=0, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO, text=message
        )
        
        response = None
        dialog.show_all()
        while response is None:
            pygame.event.pump()
            if self.joystick:
                if self.joystick.get_button(0):
                    response = Gtk.ResponseType.YES
                    pygame.time.wait(200)
                elif self.joystick.get_button(1):
                    response = Gtk.ResponseType.NO
                    pygame.time.wait(200)
            Gtk.main_iteration_do(False)
            if response is None:
                response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            process_dialog = Gtk.MessageDialog(
                transient_for=self, flags=0, message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.NONE, text="Processing..."
            )
            progress_bar = Gtk.ProgressBar()
            process_dialog.get_content_area().pack_start(progress_bar, True, True, 0)
            process_dialog.show_all()

            def update_progress(fraction, game_name, dialog, progress_bar):
                progress_bar.set_fraction(fraction)
                dialog.set_property("text", f"Processing: {game_name}")
                while Gtk.events_pending():
                    Gtk.main_iteration()
                return False

            def reset_checkboxes():
                for row in self.store:
                    row[0] = False
                return False

            def process_next_action(actions, index, total, dialog, progress_bar):
                if index >= len(actions):
                    GLib.idle_add(update_progress, 1.0, "Finishing...", dialog, progress_bar)
                    GLib.timeout_add(500, dialog.destroy)
                    GLib.idle_add(self.show_info, "Success: All actions completed")
                    GLib.idle_add(reset_checkboxes)
                    return False
                
                treeiter, appid, selected_folder, target_path, action, game_name = actions[index]
                GLib.idle_add(update_progress, index / total, game_name, dialog, progress_bar)
                GLib.timeout_add(50, lambda: perform_action(treeiter, selected_folder, target_path, actions, index, total, dialog, progress_bar))
                return False

            def perform_action(treeiter, selected_folder, target_path, actions, index, total, dialog, progress_bar):
                try:
                    toggle_symlink(selected_folder, target_path)
                    self.store[treeiter][4] = is_symlink(selected_folder)
                except Exception as e:
                    GLib.idle_add(dialog.destroy)
                    GLib.idle_add(self.show_error, f"Error processing {self.store[treeiter][2]}: {str(e)}")
                    return False
                GLib.timeout_add(100, process_next_action, actions, index + 1, total, dialog, progress_bar)
                return False

            GLib.timeout_add(500, process_next_action, actions, 0, len(actions), process_dialog, progress_bar)

    def show_info(self, message):
        dialog = Gtk.MessageDialog(
            transient_for=self, flags=0, message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK, text=message
        )
        dialog.run()
        dialog.destroy()
        return False

    def handle_gamepad(self):
        if not self.joystick:
            return True

        pygame.event.pump()
        current_path = self.treeview.get_cursor()[0] or Gtk.TreePath.new_first()

        if self.joystick.get_numhats() > 0:
            hat_y = self.joystick.get_hat(0)[1]
            if hat_y == 1 and current_path.get_indices()[0] > 0:
                new_path = Gtk.TreePath.new_from_indices([current_path.get_indices()[0] - 1])
                self.treeview.set_cursor(new_path)
                pygame.time.wait(200)
            elif hat_y == -1 and current_path.get_indices()[0] < len(self.store) - 1:
                new_path = Gtk.TreePath.new_from_indices([current_path.get_indices()[0] + 1])
                self.treeview.set_cursor(new_path)
                pygame.time.wait(200)

        y_axis = self.joystick.get_axis(1)
        if y_axis < -0.95 and current_path.get_indices()[0] > 0:
            new_path = Gtk.TreePath.new_from_indices([current_path.get_indices()[0] - 1])
            self.treeview.set_cursor(new_path)
            pygame.time.wait(200)
        elif y_axis > 0.95 and current_path.get_indices()[0] < len(self.store) - 1:
            new_path = Gtk.TreePath.new_from_indices([current_path.get_indices()[0] + 1])
            self.treeview.set_cursor(new_path)
            pygame.time.wait(200)

        selection = self.treeview.get_selection()
        model, treeiter = selection.get_selected()
        if self.joystick.get_button(0) and treeiter:
            self.toggle_location([treeiter])

        return True

if __name__ == "__main__":
    win = ProtonManagerWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    pygame.quit()