# Auxlink

**Auxlink** is a modifier preset manager and workflow enhancement tool for **Blender 5.0+** (and Blender 4.2+). It lets you save complex modifier stacks as named presets, edit and reorder presets directly from Blender Preferences, re-apply them to any selected object with a single click, and import/export presets in clean, human-readable YAML format without any external Python dependencies.

Auxlink also includes **Auto Lattice**, designed specifically for fast deformation and shaping of **Skin modifier** meshes and character blockouts.

---

## What's New in v1.1.0

- 🎛️ **Preferences Preset Editor**:
  - Click any preset in Preferences to inspect its modifier stack.
  - Reorder modifiers inside presets using Up (▲) / Down (▼) buttons.
  - Rename modifiers inside presets or rename the presets themselves.
  - Delete individual modifiers from presets.
  - Duplicate presets with one click.
  - Overwrite presets directly from the active object's current modifier stack.
- 📦 **Built-in Default Presets**:
  - Ships with factory presets tuned for organic and character skin modeling (`Organic`, `Ring`, `Character`, `Basic`, `Hardskin`, `Preciseskin`, `Ballskin`).
  - Auto-loaded on fresh installations; can be restored or merged anytime via the **Restore Defaults** button.
- 📐 **Auto Lattice Tool**:
  - Automatically calculates the evaluated bounding box of meshes (including Skin, Subdivision, Bevel, etc.).
  - Creates a bounding Lattice object with configurable U/V/W resolution (default 3x3x3), padding margin, and smooth B-Spline interpolation.
  - Inserts the Lattice modifier right after the `Skin` modifier (before `Subdivision` for ultra-smooth deformation).
  - Automatically enters Edit Mode on the Lattice so you can start shaping immediately with Grab/Scale/Rotate.
  - Includes **Apply Lattice** and **Remove Lattice** helper operators in the Auxlink menu.

---

## Installation

### Method 1: Drag & Drop (Recommended)
1. Download `auxlink-1.1.0.zip` (or `auxlink.zip`).
2. Drag and drop the `.zip` file directly into the Blender 5.0 viewport.
3. Click **Install Extension** when prompted.

### Method 2: Install from Disk
1. Open Blender 5.0.
2. Go to **Edit > Preferences > Get Extensions**.
3. Click the menu icon (arrow in top right corner) and select **Install from Disk...**.
4. Select `auxlink-1.1.0.zip` (or `auxlink.zip`) and click **Install**.

---

## Features & Usage

### 1. Saving & Applying Modifier Presets
- **Save Preset**: Select an object with modifiers, **Right-click** > **Auxlink** > **Save Modifier Preset**.
- **Apply Preset**: Select one or more objects, **Right-click** > **Auxlink** > **Add Modifier Preset** > choose preset.

### 2. Editing Presets in Preferences
- Go to **Edit > Preferences > Extensions > Auxlink**.
- Click the arrow next to any preset to open the inline stack editor:
  - **Move Modifiers**: Use ▲ and ▼ to change the modifier order inside the preset.
  - **Rename / Remove**: Modify names or delete unwanted modifiers from the preset.
  - **Update from Active Object**: Replace the preset stack with the active object's current modifiers.
  - **Duplicate / Delete**: Clone presets or remove them.
- Use **Restore Defaults** to recover factory presets (`Organic`, `Hardskin`, etc.).
- Use **Import / Export YAML** to share presets with colleagues or back them up.
- Click **Edit in Text Editor** to open `presets.yaml` directly in your favorite editor.

### 3. Auto Lattice (Deform Skin Meshes)
- Select your mesh (especially useful for meshes built with `Skin` modifier).
- **Right-click** > **Auxlink** > **Auto Lattice (Fit to Mesh)**.
- Adjust parameters in the Operator panel if needed (Resolution U/V/W, padding margin, interpolation).
- Blender switches directly to Lattice Edit Mode: tweak control points to pose or deform your model!
- When satisfied:
  - **Right-click** > **Auxlink** > **Apply Lattice** (applies deformation and cleans up the lattice object).
  - Or **Remove Lattice** to revert without applying.

---

## Supported Blender Versions

- Blender **5.0+**
- Blender **4.2+**

---

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
