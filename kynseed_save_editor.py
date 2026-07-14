#!/usr/bin/env python3
"""Kynseed Save Editor - inventory-focused XML editor.

Built for Kynseed save XML format seen in SaveVersion 49 / game 1.3.x.
Uses only Python's standard library (Tkinter + ElementTree).
"""
from __future__ import annotations

import csv
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_NAME = "Kynseed Save Editor"
QUALITY_LABELS = ("1★", "2★", "3★", "4★", "5★")

# Internal/helper item records that are not useful for normal inventory editing.
HIDDEN_ITEM_NAME_PATTERNS = (
    re.compile(r"\blocation\s*\d+\b", re.IGNORECASE),
    re.compile(r"\buse\b", re.IGNORECASE),
)


def is_hidden_item_name(name: str) -> bool:
    """Return True for internal Location-number and Use helper entries."""
    return any(pattern.search(name) for pattern in HIDDEN_ITEM_NAME_PATTERNS)


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child(parent: Optional[ET.Element], name: str) -> Optional[ET.Element]:
    if parent is None:
        return None
    for node in parent:
        if local_name(node.tag) == name:
            return node
    return None


def children(parent: Optional[ET.Element], name: str) -> list[ET.Element]:
    if parent is None:
        return []
    return [n for n in parent if local_name(n.tag) == name]


def text_of(parent: Optional[ET.Element], name: str, default: str = "") -> str:
    node = child(parent, name)
    return (node.text or default).strip() if node is not None else default


def descendant(parent: Optional[ET.Element], path: list[str]) -> Optional[ET.Element]:
    node = parent
    for part in path:
        node = child(node, part)
        if node is None:
            return None
    return node


def count_nodes(count_el: Optional[ET.Element]) -> list[ET.Element]:
    if count_el is None:
        return []
    nodes = children(count_el, "int")
    while len(nodes) < 5:
        n = ET.SubElement(count_el, "int")
        n.text = "0"
        nodes.append(n)
    return nodes[:5]


def safe_int(value: str, default: int = 0) -> int:
    try:
        return int((value or "").strip())
    except (TypeError, ValueError):
        return default


@dataclass
class InventoryRow:
    source: str
    category: str
    item_id: int
    name: str
    count_elements: list[ET.Element]
    bottle_content: str = ""
    bottle_rating: str = ""

    @property
    def counts(self) -> list[int]:
        return [safe_int(n.text or "0") for n in self.count_elements]

    @property
    def total(self) -> int:
        return sum(self.counts)


class SaveModel:
    def __init__(self, item_names: dict[int, str]):
        self.item_names = item_names
        self.path: Optional[Path] = None
        self.tree: Optional[ET.ElementTree] = None
        self.root: Optional[ET.Element] = None
        self.dirty = False
        self.build_version = ""
        self.save_version = ""
        self.player_name = "Player"
        self.rows_by_source: dict[str, list[InventoryRow]] = {}
        self.source_labels: dict[str, str] = {}

    def load(self, path: Path) -> None:
        tree = ET.parse(path)
        root = tree.getroot()
        if local_name(root.tag) != "GameSaveData":
            raise ValueError("This does not look like a Kynseed GameSaveData XML file.")
        self.path, self.tree, self.root = path, tree, root
        self.build_version = text_of(root, "BuildVersion", "Unknown")
        self.save_version = text_of(root, "SaveVersion", "Unknown")
        player_data = child(root, "PlayerData")
        self.player_name = text_of(player_data, "Name", "Player")
        self.rows_by_source = {}
        self.source_labels = {}
        self._load_player_inventory(player_data)
        self._load_home_larder(player_data)
        self._load_owned_shops(root)
        self.dirty = False

    def _item_name(self, item_id: int) -> str:
        return self.item_names.get(item_id, f"Unknown item {item_id}")

    def _load_player_inventory(self, player_data: Optional[ET.Element]) -> None:
        all_items = descendant(player_data, ["Inventory", "AllItems"])
        rows: list[InventoryRow] = []
        for entry in children(all_items, "item"):
            key = descendant(entry, ["key", "int"])
            count_el = descendant(entry, ["value", "InventoryItem", "Count"])
            if key is None or count_el is None:
                continue
            item_id = safe_int(key.text or "-1", -1)
            rows.append(InventoryRow(
                source="player",
                category="Character Inventory",
                item_id=item_id,
                name=self._item_name(item_id),
                count_elements=count_nodes(count_el),
            ))
        self.rows_by_source["player"] = rows
        self.source_labels["player"] = f"{self.player_name} — Inventory"

    def _load_home_larder(self, player_data: Optional[ET.Element]) -> None:
        """Load the household larder stored under PlayerData/newLarder."""
        larder = child(player_data, "newLarder")
        if larder is None:
            return
        source = "home_larder"
        self.rows_by_source[source] = self._rows_from_larder(source, larder)
        self.source_labels[source] = "Home Larder"

    def _load_owned_shops(self, root: ET.Element) -> None:
        owned_node = next((n for n in root.iter() if local_name(n.tag) == "ShopsOwned"), None)
        owned_ids = {safe_int(n.text or "-1", -1) for n in children(owned_node, "int")}
        saved_shops = child(root, "SavedShops")
        for shop in children(saved_shops, "Shop"):
            home_id = safe_int(text_of(shop, "HomeID", "-1"), -1)
            if home_id not in owned_ids:
                continue
            shop_name = text_of(shop, "Name", f"Shop {home_id}")
            shop_type = text_of(shop, "typeOfShop", "Shop")
            for larder_name, pretty in (
                ("Larder_Materials", "Materials / Stock"),
                ("Larder_CraftedShelf", "Crafted Shelf"),
                ("Larder_BlacksmithOrders", "Blacksmith Orders"),
            ):
                larder = child(shop, larder_name)
                if larder is None:
                    continue
                source = f"shop:{home_id}:{larder_name}"
                rows = self._rows_from_larder(source, larder)
                # Keep even empty larders so the structure remains discoverable.
                self.rows_by_source[source] = rows
                self.source_labels[source] = f"{shop_name} ({shop_type}) — {pretty}"

    def _rows_from_larder(self, source: str, larder: ET.Element) -> list[InventoryRow]:
        rows: list[InventoryRow] = []
        stacks_root = child(larder, "stacks")
        for group in children(stacks_root, "item"):
            category = text_of(child(group, "key"), "string", "Uncategorized")
            stack_list = descendant(group, ["value", "StackList"])
            stacks = child(stack_list, "Stacks")
            for stack in children(stacks, "ItemStack"):
                uid = child(stack, "UniqueID")
                count_el = child(stack, "Count")
                if uid is None or count_el is None:
                    continue
                item_id = safe_int(uid.text or "-1", -1)
                rows.append(InventoryRow(
                    source=source,
                    category=category,
                    item_id=item_id,
                    name=self._item_name(item_id),
                    count_elements=count_nodes(count_el),
                    bottle_content=text_of(stack, "BottleContent", ""),
                    bottle_rating=text_of(stack, "BottleContentRating", ""),
                ))
        return rows

    def save(self, target: Optional[Path] = None, make_backup: bool = True) -> Path:
        if self.tree is None or self.path is None:
            raise RuntimeError("No save file is loaded.")
        target = target or self.path
        if make_backup and target.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = target.with_name(f"{target.stem}.backup_{stamp}{target.suffix}")
            shutil.copy2(target, backup)
        # Register the namespace already used by Kynseed so xsi:nil remains tidy.
        ET.register_namespace("xsi", "http://www.w3.org/2001/XMLSchema-instance")
        ET.register_namespace("xsd", "http://www.w3.org/2001/XMLSchema")
        self.tree.write(target, encoding="utf-8", xml_declaration=True, short_empty_elements=True)
        self.path = target
        self.dirty = False
        return target


class InventoryPanel(ttk.Frame):
    def __init__(self, master: tk.Widget, app: "EditorApp", source: str):
        super().__init__(master, padding=8)
        self.app = app
        self.source = source
        self.visible_rows: list[InventoryRow] = []
        self.search_var = tk.StringVar()
        self.show_zero_var = tk.BooleanVar(value=False)
        self.quality_vars = [tk.StringVar(value="0") for _ in range(5)]
        self.selected_row: Optional[InventoryRow] = None
        self._build()
        self.refresh()

    def _build(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Search item name or ID:").pack(side="left")
        search = ttk.Entry(top, textvariable=self.search_var, width=32)
        search.pack(side="left", padx=(6, 12))
        search.bind("<KeyRelease>", lambda _e: self.refresh())
        ttk.Checkbutton(top, text="Show zero-count entries", variable=self.show_zero_var,
                        command=self.refresh).pack(side="left")
        ttk.Button(top, text="Clear", command=lambda: self.search_var.set("" ) or self.refresh()).pack(side="right")

        cols = ("id", "name", "category", "q1", "q2", "q3", "q4", "q5", "total")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        headings = {"id":"ID", "name":"Item", "category":"Category", "q1":"1★", "q2":"2★", "q3":"3★", "q4":"4★", "q5":"5★", "total":"Total"}
        widths = {"id":70, "name":210, "category":210, "q1":58, "q2":58, "q3":58, "q4":58, "q5":58, "total":70}
        for col in cols:
            self.tree.heading(col, text=headings[col], command=lambda c=col: self._sort(c, False))
            self.tree.column(col, width=widths[col], anchor="w" if col in {"name","category"} else "center")
        ybar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        xbar = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.tree.pack(side="top", fill="both", expand=True)
        ybar.place(relx=1.0, rely=0.075, relheight=0.68, anchor="ne")
        xbar.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        editor = ttk.LabelFrame(self, text="Edit selected item", padding=8)
        editor.pack(fill="x", pady=(8, 0))
        self.selected_label = ttk.Label(editor, text="Select an item above.")
        self.selected_label.grid(row=0, column=0, columnspan=7, sticky="w", pady=(0, 6))
        for i, label in enumerate(QUALITY_LABELS):
            ttk.Label(editor, text=label).grid(row=1, column=i, padx=4)
            entry = ttk.Entry(editor, textvariable=self.quality_vars[i], width=9, justify="center")
            entry.grid(row=2, column=i, padx=4)
        ttk.Button(editor, text="Apply counts", command=self.apply_counts).grid(row=2, column=5, padx=(14, 4))
        ttk.Button(editor, text="Set all to 100", command=self.set_all_100).grid(row=2, column=6, padx=4)

    def refresh(self) -> None:
        query = self.search_var.get().strip().lower()
        show_zero = self.show_zero_var.get()
        rows = self.app.model.rows_by_source.get(self.source, [])
        self.visible_rows = [
            r for r in rows
            if not is_hidden_item_name(r.name)
            and (show_zero or r.total > 0)
            and (not query or query in r.name.lower() or query in str(r.item_id) or query in r.category.lower())
        ]
        self.tree.delete(*self.tree.get_children())
        for idx, row in enumerate(self.visible_rows):
            counts = row.counts
            self.tree.insert("", "end", iid=str(idx), values=(row.item_id, row.name, row.category, *counts, sum(counts)))

    def _sort(self, col: str, reverse: bool) -> None:
        mapping = {"id": lambda r:r.item_id, "name":lambda r:r.name.lower(), "category":lambda r:r.category.lower(),
                   "q1":lambda r:r.counts[0], "q2":lambda r:r.counts[1], "q3":lambda r:r.counts[2],
                   "q4":lambda r:r.counts[3], "q5":lambda r:r.counts[4], "total":lambda r:r.total}
        self.visible_rows.sort(key=mapping[col], reverse=reverse)
        self.tree.delete(*self.tree.get_children())
        for idx, row in enumerate(self.visible_rows):
            c=row.counts
            self.tree.insert("", "end", iid=str(idx), values=(row.item_id,row.name,row.category,*c,sum(c)))
        self.tree.heading(col, command=lambda c=col: self._sort(c, not reverse))

    def _on_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        row = self.visible_rows[int(selection[0])]
        self.selected_row = row
        extra = f" — Bottle: {row.bottle_content} ({row.bottle_rating}★)" if row.bottle_content else ""
        self.selected_label.configure(text=f"ID {row.item_id}: {row.name}  |  {row.category}{extra}")
        for var, value in zip(self.quality_vars, row.counts):
            var.set(str(value))

    def apply_counts(self) -> None:
        if self.selected_row is None:
            messagebox.showinfo(APP_NAME, "Select an inventory item first.", parent=self)
            return
        values: list[int] = []
        for var in self.quality_vars:
            try:
                value = int(var.get())
                if value < 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(APP_NAME, "Counts must be whole numbers of 0 or greater.", parent=self)
                return
            values.append(value)
        for node, value in zip(self.selected_row.count_elements, values):
            node.text = str(value)
        self.app.model.dirty = True
        self.app.update_title()
        self.refresh()
        # Reselect row if still visible.
        try:
            idx = self.visible_rows.index(self.selected_row)
            self.tree.selection_set(str(idx))
            self.tree.see(str(idx))
        except ValueError:
            self.selected_row = None

    def set_all_100(self) -> None:
        for var in self.quality_vars:
            var.set("100")
        self.apply_counts()


class EditorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.geometry("1180x760")
        self.minsize(900, 600)
        self.item_names = self._load_item_names()
        self.model = SaveModel(self.item_names)
        self.panels: list[InventoryPanel] = []
        self._build_menu()
        self._build_shell()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_title()

    def _load_item_names(self) -> dict[int, str]:
        paths = [app_dir() / "item_ids.csv", app_dir() / "Kynseed_item_IDs.csv"]
        for path in paths:
            if path.exists():
                names: dict[int, str] = {}
                with path.open("r", encoding="utf-8-sig", newline="") as f:
                    for row in csv.DictReader(f):
                        try:
                            names[int(row["item_id"])] = row["name"]
                        except (KeyError, ValueError):
                            pass
                return names
        return {}

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Open save…", accelerator="Ctrl+O", command=self.open_save)
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save)
        file_menu.add_command(label="Save as…", command=self.save_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close)
        menubar.add_cascade(label="File", menu=file_menu)
        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="About", command=self.about)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.configure(menu=menubar)
        self.bind_all("<Control-o>", lambda _e: self.open_save())
        self.bind_all("<Control-s>", lambda _e: self.save())

    def _build_shell(self) -> None:
        header = ttk.Frame(self, padding=(10, 8))
        header.pack(fill="x")
        self.status = ttk.Label(header, text="Open a Kynseed XML save to begin.")
        self.status.pack(side="left")
        ttk.Button(header, text="Open save…", command=self.open_save).pack(side="right")
        ttk.Button(header, text="Save", command=self.save).pack(side="right", padx=6)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        welcome = ttk.Frame(self.notebook, padding=24)
        ttk.Label(welcome, text="Kynseed Save Editor", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(welcome, text="Inventory-focused editor for character, home-larder, and owned-shop stock.\n\n"
                                      "Open Slot1_Autosave.xml (or another slot XML). The editor automatically detects your owned shops, "
                                      "maps item IDs to names, includes your household larder, and creates a timestamped backup whenever you save.",
                  wraplength=760, justify="left").pack(anchor="w", pady=12)
        ttk.Label(welcome, text="Important: close Kynseed before editing. Keep backups. This is an unofficial community tool.",
                  wraplength=760, justify="left").pack(anchor="w")
        self.notebook.add(welcome, text="Welcome")

    def update_title(self) -> None:
        suffix = ""
        if self.model.path:
            suffix = f" — {self.model.path.name}"
        if self.model.dirty:
            suffix += " *"
        self.title(APP_NAME + suffix)

    def maybe_discard(self) -> bool:
        if not self.model.dirty:
            return True
        answer = messagebox.askyesnocancel(APP_NAME, "Save your changes before continuing?")
        if answer is None:
            return False
        if answer:
            return self.save()
        return True

    def open_save(self) -> None:
        if not self.maybe_discard():
            return
        filename = filedialog.askopenfilename(title="Open Kynseed save", filetypes=[("Kynseed XML saves", "*.xml"), ("All files", "*.*")])
        if not filename:
            return
        try:
            self.model.load(Path(filename))
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not open the save:\n\n{exc}")
            return
        self.rebuild_tabs()
        self.status.configure(text=f"{self.model.player_name} | Build {self.model.build_version} | Save v{self.model.save_version} | {filename}")
        self.update_title()

    def rebuild_tabs(self) -> None:
        for tab in self.notebook.tabs():
            self.notebook.forget(tab)
        self.panels = []
        # Player first, then home larder, then owned shop sources.
        sources = list(self.model.rows_by_source)
        order = {"player": 0, "home_larder": 1}
        sources.sort(key=lambda s: (order.get(s, 2), self.model.source_labels.get(s, s)))
        for source in sources:
            rows = self.model.rows_by_source[source]
            if source != "player" and not rows:
                continue
            panel = InventoryPanel(self.notebook, self, source)
            label = self.model.source_labels.get(source, source)
            # Keep tabs readable; full label remains in status via tooltip unavailable in stock Tk.
            short = label.replace(" — Materials / Stock", " — Stock").replace(" — Character Inventory", "")
            if len(short) > 34:
                short = short[:31] + "…"
            self.notebook.add(panel, text=short)
            self.panels.append(panel)

    def save(self) -> bool:
        if self.model.path is None:
            return self.save_as()
        try:
            target = self.model.save(make_backup=True)
            self.update_title()
            self.status.configure(text=f"Saved {target} (timestamped backup created).")
            messagebox.showinfo(APP_NAME, f"Save written successfully.\n\nA timestamped backup was created beside the save file.")
            return True
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not save:\n\n{exc}")
            return False

    def save_as(self) -> bool:
        filename = filedialog.asksaveasfilename(title="Save Kynseed XML", defaultextension=".xml",
                                                filetypes=[("XML files", "*.xml"), ("All files", "*.*")],
                                                initialfile=self.model.path.name if self.model.path else "Slot1_Autosave.xml")
        if not filename:
            return False
        try:
            target = self.model.save(Path(filename), make_backup=True)
            self.update_title()
            self.status.configure(text=f"Saved as {target}")
            return True
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"Could not save:\n\n{exc}")
            return False

    def about(self) -> None:
        messagebox.showinfo(APP_NAME, "Kynseed Save Editor\n\nInventory-focused unofficial editor.\n"
                           f"Loaded item names: {len(self.item_names):,}\n\n"
                           "Edits existing character, home-larder, and owned-shop inventory entries. It does not recalculate Kynseed checksum fields.")

    def on_close(self) -> None:
        if self.maybe_discard():
            self.destroy()


if __name__ == "__main__":
    EditorApp().mainloop()
