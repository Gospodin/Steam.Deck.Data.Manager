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
SHADERCACHE_PATH = Path("/home/deck/.steam/steam/steamapps/shadercache")

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
TARGET_COMPATDATA_DIR = MICROSD_PATH / "compatdata" if MICROSD_PATH else None
TARGET_SHADERCACHE_DIR = MICROSD_PATH / "shadercache" if MICROSD_PATH else None

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

def get_shader_size(appid):
    shader_path = SHADERCACHE_PATH / appid
    if shader_path.exists():
        return get_folder_size(shader_path)
    return 0.0

def get_game_icon(appid):
    base_path = Path(f"/home/deck/.steam/steam/appcache/librarycache/{appid}")
    preferred_files = ["header.jpg", "logo.png", "library_header.png"]
    
    for filename in preferred_files:
        icon_path = base_path / filename
        if icon_path.exists():
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(icon_path), -1, 48, True)  # Уменьшено до 48
                return pixbuf
            except Exception:
                pass

    if base_path.exists():
        for file in base_path.iterdir():
            if file.is_file() and file.suffix.lower() in [".jpg", ".png"]:
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(file), -1, 48, True)  # Уменьшено до 48
                    return pixbuf
                except Exception:
                    pass
    
    return None

def is_symlink(path):
    return os.path.islink(path)

def get_storage_location(appid):
    prefix_path = COMPATDATA_PATH / appid
    shader_path = SHADERCACHE_PATH / appid
    prefix_loc = str(prefix_path) if not is_symlink(prefix_path) else os.readlink(prefix_path)
    shader_loc = str(shader_path) if not is_symlink(shader_path) else os.readlink(shader_path) if shader_path.exists() else "N/A"
    prefix_label = f"Prefix: {prefix_loc} ({'Internal' if not is_symlink(prefix_path) else 'microSD'})"
    shader_label = f"Shader: {shader_loc} ({'Internal' if not is_symlink(shader_path) else 'microSD' if shader_path.exists() else 'N/A'})"
    return f"{prefix_label}\n{shader_label}"

def toggle_symlink(source_path, target_path):
    if not target_path:
        raise Exception("No SD card detected!")
    if is_symlink(source_path):
        link_target = Path(os.readlink(source_path))
        os.unlink(source_path)
        if link_target.exists():
            shutil.move(link_target, source_path)
        return "Moved back to internal storage"
    else:
        if not target_path.parent.exists():
            target_path.parent.mkdir(parents=True)
        shutil.move(source_path, target_path)
        os.symlink(target_path, source_path)
        return "Moved to target with symlink"

def delete_folder(path):
    if is_symlink(path):
        link_target = Path(os.readlink(path))
        os.unlink(path)
        if link_target.exists():
            shutil.rmtree(link_target)
        return "Symlink and target folder deleted"
    elif path.exists():
        shutil.rmtree(path)
        return "Folder deleted"
    return "Nothing to delete"

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
        super().__init__(title="Steam Deck Data Manager")
        self.set_default_size(1280, 800)  # Фиксированный размер для Steam Deck

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

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)  # Уменьшено spacing
        self.add(vbox)

        label = Gtk.Label(label=f"Using SD card: {MICROSD_PATH}")
        label.set_margin_top(5)
        label.set_margin_bottom(5)
        vbox.pack_start(label, False, False, 0)

        self.progress = Gtk.ProgressBar()
        self.progress_label = Gtk.Label(label="Loading games...")
        vbox.pack_start(self.progress_label, False, False, 0)
        vbox.pack_start(self.progress, False, False, 0)

        self.store = Gtk.ListStore(bool, str, str, float, float, bool, GdkPixbuf.Pixbuf)
        self.treeview = Gtk.TreeView(model=self.store)
        self.treeview.set_fixed_height_mode(True)
        
        renderer_toggle = Gtk.CellRendererToggle()
        renderer_toggle.connect("toggled", self.on_toggle_selection)
        column_toggle = Gtk.TreeViewColumn("Select", renderer_toggle, active=0)
        column_toggle.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        column_toggle.set_fixed_width(40)  # Уменьшено с 50
        self.treeview.append_column(column_toggle)

        renderer_icon = Gtk.CellRendererPixbuf()
        renderer_icon.set_padding(0, 0)
        column_icon = Gtk.TreeViewColumn("Icon", renderer_icon, pixbuf=6)
        column_icon.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
        column_icon.set_fixed_width(150)  # Уменьшено с 200
        self.treeview.append_column(column_icon)

        columns = ["AppID", "Game Name", "Size\n(MB)", "Shader\nSize (MB)", "Location"]
        for i, column_title in enumerate(columns):
            renderer = Gtk.CellRendererText()
            renderer.set_padding(0, 0)
            renderer.set_fixed_height_from_font(1)
            renderer.set_property("scale", 0.9)  # Уменьшен масштаб текста
            if column_title == "Location":
                renderer.set_property("wrap-width", 250)  # Уменьшено с 300
                renderer.set_property("wrap-mode", Pango.WrapMode.WORD)
                column = Gtk.TreeViewColumn(column_title, renderer, markup=i + 1)
                column.set_cell_data_func(renderer, self.format_location)
            elif column_title == "Game Name":
                renderer.set_property("wrap-width", 150)  # Уменьшено с 200
                renderer.set_property("wrap-mode", Pango.WrapMode.WORD)
                column = Gtk.TreeViewColumn(column_title, renderer, text=i + 1)
            else:
                column = Gtk.TreeViewColumn(column_title, renderer, text=i + 1)
            column.set_sizing(Gtk.TreeViewColumnSizing.FIXED)
            column.set_sort_column_id(i + 1)
            if column_title == "AppID":
                column.set_fixed_width(80)  # Уменьшено с 100
                self.store.set_sort_func(1, self.string_sort_func, None)
            elif column_title == "Game Name":
                column.set_fixed_width(150)  # Уменьшено с 200
                self.store.set_sort_func(2, self.string_sort_func, None)
            elif column_title == "Size\n(MB)":
                column.set_fixed_width(50)  # Уменьшено с 67
                renderer.set_property("xalign", 1.0)
                column.set_cell_data_func(renderer, lambda col, cell, model, iter, data: cell.set_property("text", f"{model[iter][3]:.2f}"))
                self.store.set_sort_func(3, self.size_sort_func, None)
            elif column_title == "Shader\nSize (MB)":
                column.set_fixed_width(50)  # Уменьшено с 67
                renderer.set_property("xalign", 1.0)
                column.set_cell_data_func(renderer, lambda col, cell, model, iter, data: cell.set_property("text", f"{model[iter][4]:.2f}"))
                self.store.set_sort_func(4, self.shader_size_sort_func, None)
            elif column_title == "Location":
                column.set_fixed_width(300)  # Уменьшено с 400
                self.store.set_sort_func(5, self.string_sort_func, None)
            self.treeview.append_column(column)

        self.treeview.connect("row-activated", self.on_row_activated)
        self.treeview.connect("button-press-event", self.on_right_click)
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.add(self.treeview)
        vbox.pack_start(scrolled_window, True, True, 0)

        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)  # Уменьшено spacing
        toggle_prefix_button = Gtk.Button(label="Toggle Selected Prefixes")
        toggle_prefix_button.connect("clicked", self.on_toggle_clicked)
        hbox.pack_start(toggle_prefix_button, True, True, 0)

        toggle_shader_button = Gtk.Button(label="Toggle Selected Shader Caches")
        toggle_shader_button.connect("clicked", self.on_toggle_shader_clicked)
        hbox.pack_start(toggle_shader_button, True, True, 0)
        vbox.pack_start(hbox, False, False, 5)  # Уменьшено padding

        self.treeview.set_cursor(Gtk.TreePath.new_first())
        GLib.timeout_add(50, self.handle_gamepad)
        GLib.timeout_add(100, self.populate_store_async)

    def format_location(self, column, cell, model, iter, data):
        appid = model[iter][1]
        text = get_storage_location(appid)
        lines = text.split("\n")
        colored_text = ""
        for line in lines:
            if "(Internal)" in line:
                colored_text += f'<span foreground="red">{line}</span>\n'
            elif "(microSD)" in line:
                colored_text += f'<span foreground="green">{line}</span>\n'
            else:
                colored_text += f"{line}\n"
        cell.set_property("markup", colored_text.strip())

    def string_sort_func(self, model, iter1, iter2, user_data):
        column_idx = model.get_sort_column_id()[0]
        val1 = model[iter1][column_idx]
        val2 = model[iter2][column_idx]
        if column_idx == 5:
            val1 = get_storage_location(model[iter1][1])
            val2 = get_storage_location(model[iter2][1])
        return -1 if val1 > val2 else (1 if val1 < val2 else 0)

    def size_sort_func(self, model, iter1, iter2, user_data):
        size1 = model[iter1][3]
        size2 = model[iter2][3]
        return -1 if size1 > size2 else (1 if size1 < size2 else 0)

    def shader_size_sort_func(self, model, iter1, iter2, user_data):
        size1 = model[iter1][4]
        size2 = model[iter2][4]
        return -1 if size1 > size2 else (1 if size1 < size2 else 0)

    def populate_store_async(self):
        total_folders = len(self.app_folders)
        seen_appids = set()
        app_list = list(self.app_folders.items())
        
        def process_batch(start_idx):
            if start_idx >= len(app_list):
                GLib.idle_add(self.progress.set_fraction, 1.0)
                GLib.idle_add(self.progress_label.set_text, "Loading complete")
                GLib.timeout_add(500, lambda: self.progress.hide() or self.progress_label.hide())
                GLib.idle_add(self.apply_initial_sort)
                return False

            end_idx = min(start_idx + 10, len(app_list))
            batch = app_list[start_idx:end_idx]
            for appid, folder in batch:
                if appid in seen_appids:
                    continue
                name = get_game_name(appid)
                GLib.idle_add(self.progress_label.set_text, f"Loading: {name}")
                size = get_folder_size(folder)
                shader_size = get_shader_size(appid)
                symlink = is_symlink(folder)
                icon = get_game_icon(appid)
                GLib.idle_add(self.add_to_store, (False, appid, name, size, shader_size, symlink, icon))
                seen_appids.add(appid)
            
            fraction = len(seen_appids) / total_folders
            GLib.idle_add(self.progress.set_fraction, fraction)
            GLib.timeout_add(50, process_batch, end_idx)
            return False

        GLib.timeout_add(50, process_batch, 0)
        return False

    def apply_initial_sort(self):
        self.store.set_sort_column_id(3, Gtk.SortType.ASCENDING)
        return False

    def add_to_store(self, data):
        selected, appid, name, size, shader_size, symlink, icon = data
        self.store.append([selected, appid, name, size, shader_size, symlink, icon])
        return False

    def on_toggle_selection(self, widget, path):
        self.store[path][0] = not self.store[path][0]

    def on_row_activated(self, treeview, path, column):
        model = treeview.get_model()
        treeiter = model.get_iter(path)
        if treeiter:
            self.toggle_location([treeiter], "prefix")

    def on_right_click(self, treeview, event):
        if event.button == 3:
            path, _, _, _ = treeview.get_path_at_pos(int(event.x), int(event.y)) or (None, None, None, None)
            if path:
                model = treeview.get_model()
                treeiter = model.get_iter(path)
                appid = model[treeiter][1]
                game_name = model[treeiter][2]

                menu = Gtk.Menu()
                move_prefix = Gtk.MenuItem(label="Move Prefix")
                move_prefix.connect("activate", lambda w: self.toggle_location([treeiter], "prefix"))
                menu.append(move_prefix)

                move_shader = Gtk.MenuItem(label="Move Shader Cache")
                move_shader.connect("activate", lambda w: self.toggle_location([treeiter], "shader"))
                menu.append(move_shader)

                delete_prefix = Gtk.MenuItem(label="Delete Prefix")
                delete_prefix.connect("activate", lambda w: self.delete_location([treeiter], "prefix"))
                menu.append(delete_prefix)

                delete_shader = Gtk.MenuItem(label="Delete Shader Cache")
                delete_shader.connect("activate", lambda w: self.delete_location([treeiter], "shader"))
                menu.append(delete_shader)

                menu.show_all()
                menu.popup(None, None, None, None, event.button, event.time)
                return True
        return False

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
                self.toggle_location([treeiter], "prefix")
        else:
            self.toggle_location(selected_rows, "prefix")

    def on_toggle_shader_clicked(self, button):
        selected_rows = [self.store.get_iter(row.path) for row in self.store if row[0]]
        if not selected_rows:
            selection = self.treeview.get_selection()
            model, treeiter = selection.get_selected()
            if treeiter:
                self.toggle_location([treeiter], "shader")
        else:
            self.toggle_location(selected_rows, "shader")

    def toggle_location(self, treeiters, location_type):
        actions = []
        for treeiter in treeiters:
            appid = self.store[treeiter][1]
            game_name = self.store[treeiter][2]
            if location_type == "prefix":
                source_path = COMPATDATA_PATH / appid
                target_path = TARGET_COMPATDATA_DIR / appid
                action = "Move prefix to microSD" if not is_symlink(source_path) else "Move prefix back to internal"
            elif location_type == "shader":
                source_path = SHADERCACHE_PATH / appid
                target_path = TARGET_SHADERCACHE_DIR / appid
                action = "Move shader cache to microSD" if not is_symlink(source_path) else "Move shader cache back to internal"
            actions.append((treeiter, appid, source_path, target_path, action, game_name))

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
                
                treeiter, appid, source_path, target_path, action, game_name = actions[index]
                GLib.idle_add(update_progress, index / total, game_name, dialog, progress_bar)
                GLib.timeout_add(50, lambda: perform_action(treeiter, source_path, target_path, actions, index, total, dialog, progress_bar))
                return False

            def perform_action(treeiter, source_path, target_path, actions, index, total, dialog, progress_bar):
                try:
                    toggle_symlink(source_path, target_path)
                    self.store[treeiter][5] = is_symlink(COMPATDATA_PATH / self.store[treeiter][1])
                except Exception as e:
                    GLib.idle_add(dialog.destroy)
                    GLib.idle_add(self.show_error, f"Error processing {self.store[treeiter][2]}: {str(e)}")
                    return False
                GLib.timeout_add(100, process_next_action, actions, index + 1, total, dialog, progress_bar)
                return False

            GLib.timeout_add(500, process_next_action, actions, 0, len(actions), process_dialog, progress_bar)

    def delete_location(self, treeiters, location_type):
        actions = []
        for treeiter in treeiters:
            appid = self.store[treeiter][1]
            game_name = self.store[treeiter][2]
            if location_type == "prefix":
                path = COMPATDATA_PATH / appid
                action = "Delete prefix"
            elif location_type == "shader":
                path = SHADERCACHE_PATH / appid
                action = "Delete shader cache"
            actions.append((treeiter, appid, path, action, game_name))

        if not actions:
            return

        message = "Are you sure you want to delete the following?\n\n"
        for _, appid, _, action, game_name in actions:
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

            def process_next_action(actions, index, total, dialog, progress_bar):
                if index >= len(actions):
                    GLib.idle_add(update_progress, 1.0, "Finishing...", dialog, progress_bar)
                    GLib.timeout_add(500, dialog.destroy)
                    GLib.idle_add(self.show_info, "Success: All actions completed")
                    return False
                
                treeiter, appid, path, action, game_name = actions[index]
                GLib.idle_add(update_progress, index / total, game_name, dialog, progress_bar)
                GLib.timeout_add(50, lambda: perform_action(treeiter, path, actions, index, total, dialog, progress_bar))
                return False

            def perform_action(treeiter, path, actions, index, total, dialog, progress_bar):
                try:
                    delete_folder(path)
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
            self.toggle_location([treeiter], "prefix")

        return True

if __name__ == "__main__":
    win = ProtonManagerWindow()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
    pygame.quit()