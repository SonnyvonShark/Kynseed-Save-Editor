KYNSEED SAVE EDITOR (inventory-focused)
=======================================

WHAT IT DOES
------------
- Opens Kynseed XML save files.
- Shows your character inventory with item names instead of only numeric IDs.
- Shows the household larder from PlayerData/newLarder, including categorized food, herbs, fish, jars, and cooked food.
- Detects shops listed in <ShopsOwned> and matches them to <SavedShops> automatically.
- Shows existing shop stock/material and crafted-shelf entries.
- Edits 1-star through 5-star item quantities.
- Searches by item name, item ID, or inventory category.
- Makes a timestamped backup beside the save every time you use Save.

REQUIREMENTS
------------
- Windows, macOS, or Linux with Python 3.10+.
- Tkinter is included in the normal Windows Python installer.

RUNNING ON WINDOWS
------------------
1. Close Kynseed completely.
2. Double-click run_editor.bat.
3. If Windows asks what program to use, install Python 3 from python.org and make sure
   "Add Python to PATH" is selected during installation.
4. Open your Slot1_Autosave.xml file.
5. Select an item, change the five quality counts, and click Apply counts.
6. Use File > Save. A backup is created automatically.

IMPORTANT NOTES
---------------
- Always close Kynseed before editing. The game may overwrite an open save.
- Keep multiple backups until you know the edited save behaves correctly.
- This tool edits existing character, home-larder, and shop inventory entries. It intentionally does not add brand-new
  XML item blocks because Kynseed inventories are divided into category-specific lists.
- The five Count values are treated as 1-star, 2-star, 3-star, 4-star, and 5-star quantities.
- The editor does not recalculate <GameChecksum> or <SaveChecksum>. Your supplied save is
  already marked MODDED, and direct XML edits have worked for you, but checksum behavior
  may differ across game versions.
- This is an unofficial tool and is not affiliated with PixelCount Studios.

FILES
-----
kynseed_save_editor.py  Main program
item_ids.csv             Item ID -> item name database extracted from your Kynseed Data folder
run_editor.bat           Windows launcher

UPDATE: Internal helper items whose names contain "Location <number>" or the separate word "Use" are hidden from inventory lists. They are not deleted from the save file.
