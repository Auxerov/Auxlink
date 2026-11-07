# Auxlink

**Auxlink** is a modifier preset manager for Blender 5.0+ (and Blender 4.2+). It lets you save complex modifier stacks as named presets, re-apply them to any selected object with a single click, and import/export presets in clean, human-readable YAML format without any external Python dependencies.

---

## Features

- **One-Click Presets**: Save the entire modifier stack (or just the active modifier) from any object as a preset.
- **Batch Application**: Apply presets to all currently selected objects at once.
- **Pure Python YAML Parser**: Embedded minimal YAML reader/writer with zero external dependencies (`PyYAML` not required).
- **Import / Export**: Share presets across machines or projects in `.yaml` files.
- **Geometry Nodes Support**: Preserves custom ID properties (Geometry Nodes inputs).
- **Blender 5.0 Extension Ready**: Full support for Blender's native extension packaging system (`blender_manifest.toml`) as well as classic add-on registration.
- **Preferences Manager**: Easily browse, delete, reload, import, and export presets from Blender Preferences.

---

## Installation

### Method 1: Drag & Drop (Recommended)
1. Download `auxlink-1.0.0.zip` (or `auxlink.zip`).
2. Drag and drop the `.zip` file directly into the Blender 5.0 viewport.
3. Click **Install Extension** when prompted.

### Method 2: Install from Disk
1. Open Blender 5.0.
2. Go to **Edit > Preferences > Get Extensions**.
3. Click the menu icon (arrow in top right corner) and select **Install from Disk...**.
4. Select `auxlink-1.0.0.zip` (or `auxlink.zip`) and click **Install**.

---

## How to Use

### 1. Saving a Preset
- Select an object that has modifiers applied.
- **Right-click** in the 3D Viewport > **Auxlink** > **Save Modifier Preset**  
  *(Also available in the 3D Viewport `Object` menu or by searching `Save Modifier Preset` via F3)*.
- Enter a preset name.
- Choose whether to save the entire stack or only the active modifier, then click **Save**.

### 2. Applying a Preset
- Select one or more target objects.
- **Right-click** in the 3D Viewport > **Auxlink** > **Add Modifier Preset** > choose your preset.
- The modifier stack will be instantly added to all selected objects.

### 3. Managing & Exporting Presets
- Go to **Edit > Preferences > Extensions > Auxlink**.
- View all saved presets and their modifier lists.
- Click **Export YAML** to backup or share presets.
- Click **Import YAML** to load presets with conflict options (`Overwrite`, `Skip`, `Replace All`).
- Click **Open Folder** to quickly browse the YAML storage directory on disk.

---

## Supported Blender Versions

- Blender **5.0+**
- Blender **4.2+**

---

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
