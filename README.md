# Auxlink

**Auxlink** is a modifier preset manager and character/organic modeling workflow tool for **Blender 5.0+** (and Blender 4.2+). It lets you save complex modifier stacks as named presets, edit and reorder presets directly from Blender Preferences, re-apply them to any selected object with a single click, and import/export presets in clean, human-readable YAML format without any external Python dependencies.

Auxlink also includes **Auto Lattice**, tuned specifically for fast, tight-fitting deformation and shaping of **Skin modifier** meshes and character blockouts.

---

## What's New in v1.1.1

- 🎛️ **Custom Grid Resolution (Columns & Rows)**:
  - Clicking **Auto Lattice** now opens an interactive dialog where you can set **Columns (U)**, **Rows (V)**, and **Height (W)** before creating the lattice.
  - Added a dedicated **Auxlink tab in the 3D Viewport Sidebar (N-panel)**: adjust columns, rows, and height live with interactive sliders!
  - Added **Adjust Grid (Cols & Rows)...** and **Refit Lattice to Mesh** in the 3D Viewport context menu (`Right-Click > Auxlink`).
- 📐 **Tight Mesh Bounding (No More Oversized Lattices)**:
  - Rebuilt the bounds calculation to evaluate the real mesh surface geometry (`eval_obj.to_mesh().vertices`).
  - Default margin set to **0% (Exact Fit)**: the lattice snaps flush to the actual surface of the model without oversized padding or artificial minimum clamping.
  - Customizable Margin slider (-50% to +200%) allows tightening or expanding the cage as needed.

---

## Key Features

- **Preferences Preset Editor**:
  - Click any preset in Preferences to inspect its modifier stack.
  - Reorder modifiers inside presets using Up (▲) / Down (▼) buttons.
  - Rename modifiers inside presets or rename the presets themselves.
  - Delete individual modifiers from presets.
  - Duplicate presets with one click.
  - Overwrite presets directly from the active object's current modifier stack.
- **Factory Default Presets**:
  - Ships with default presets tuned for organic and character skin modeling (`Organic`, `Ring`, `Character`, `Basic`, `Hardskin`, `Preciseskin`, `Ballskin`).
  - Auto-loaded on fresh installations; can be restored or merged anytime via the **Restore Defaults** button.
- **Auto Lattice**:
  - Computes exact evaluated mesh bounds (including Skin, Subdivision, Bevel, etc.).
  - Configurable U/V/W resolution (Columns, Rows, Height) with smooth B-Spline interpolation.
  - Inserts the Lattice modifier right after the `Skin` modifier (before `Subdivision` for ultra-smooth deformation).
  - Automatically enters Edit Mode on the Lattice so you can start shaping immediately with Grab/Scale/Rotate.
  - Includes **Apply Lattice** and **Remove Lattice** helper operators in the Auxlink menu and N-panel.

---

## Installation

### For Users
1. Download `auxlink.zip` from [Releases](https://github.com/Auxerov/Auxlink/releases).
2. Drag and drop the `.zip` file directly into Blender 5.0 (or install via `Preferences > Get Extensions > Install from Disk...`).

### For Local Development
- Run `./build.sh` to update packages, sync default presets, and link `/home/auxerov/Auxlink` directly into Blender's user extension directory (`~/.config/blender/5.0/extensions/user_default/auxlink`).

---

## How to Use

### 1. Auto Lattice (Deform Skin Meshes)
- Select your mesh (especially useful for meshes built with `Skin` modifier).
- **Right-click** in 3D Viewport > **Auxlink** > **Auto Lattice (Fit to Mesh)...**  
  *(Also available in the 3D Viewport Sidebar `N` panel under the **Auxlink** tab)*.
- Set your desired Columns (U), Rows (V), Height (W), and Margin.
- Click **Create Lattice**; Blender enters Lattice Edit Mode with control points flush to your model.
- Tweak points to pose or shape your creature/character.
- When done, click **Apply Lattice** or **Remove Lattice** from the Auxlink menu or N-panel.

### 2. Saving & Applying Modifier Presets
- **Save Preset**: Select an object with modifiers, **Right-click** > **Auxlink** > **Save Modifier Preset**.
- **Apply Preset**: Select one or more objects, **Right-click** > **Auxlink** > **Add Modifier Preset** > choose preset.

### 3. Managing Presets in Preferences
- Go to **Edit > Preferences > Extensions > Auxlink**.
- Reorder modifiers, rename presets, duplicate, or restore defaults.

---

## Supported Blender Versions

- Blender **5.0+**
- Blender **4.2+**

---

## License

This project is licensed under the [GNU General Public License v3.0](LICENSE).
