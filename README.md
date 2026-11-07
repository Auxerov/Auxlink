# Auxlink

**Auxlink** is a modifier preset manager and character/organic modeling workflow tool for **Blender 5.0+** (and Blender 4.2+). It lets you save complex modifier stacks as named presets, edit and reorder presets directly from Blender Preferences, re-apply them to any selected object with a single click, and import/export presets in clean, human-readable YAML format without any external Python dependencies.

Auxlink also includes **Autolattice**, tuned specifically for fast, tight-fitting deformation and shaping of **Skin modifier** meshes and character blockouts.

---

## What's New in v1.2.6

- 🚀 **Instant Lattice Visibility & Auto Edit Mode**:
  - Autolattice now automatically enters Lattice Edit Mode upon creation with points highlighted, immediately visible, and ready to deform.
  - Automatically cleans up any stale or broken lattices on the mesh before creating a pristine new one.
  - Added minimum thickness guard (`min_thick`) preventing 2D/flat models from collapsing to invisible sheets.
  - Fixed subselection bug where residual Object Mode vertex selections could collapse lattice bounds.
  - Available everywhere: Right-Click (Object & Edit Mode), Shift+A Add Menu, Top Object Menu, and N-Panel.

---

## What's New in v1.2.5

- 🧊 **Standard Normal Lattice Default (2x2x2)**:
  - Autolattice now assigns a standard clean 8-corner bounding cage (`2x2x2`) fitted to the model (1.3x circumference).
  - Control points (U/V/W) can then be subdivided cleanly inside the locked cage boundary via the sidebar (N-Panel) or Lattice properties.
  - Interactive invoke automatically preserves existing subdivision counts instead of overwriting them.

---

## What's New in v1.2.4

- 🔒 **Locked Cage Boundary with Pure Internal Subdivision**:
  - Tweaking Columns (U), Rows (V), or Height (W) now **strictly subdivides inside the existing cage** without altering the cage scale, position, or outer bounding box. No multiplying, exploding, or layer jumping.
  - Sub-selection bounds in Edit Mode are preserved across operator redo ticks, preventing the cage from expanding to the whole model when adjusting resolution.
- 🎚️ **Single-Layer (2D) Support (`min=1`)**:
  - Minimum resolution is now `1` across all axes (`min=1`). Setting Height (W) to 1 gives a true single-layer 2D lattice plane for flat deformation without unwanted 3D volume tiers.
- 📐 **Deformer-Isolated Bounds Calculation**:
  - Automatically isolates evaluated base geometry from existing lattice modifiers during recalculation to eliminate compounding scale loops.

---

## What's New in v1.2.3

- 🧊 **Default 3x3x3 Resolution with Pure Internal Subdivision**:
  - Restored default resolution to **3x3x3 (`U=3, V=3, W=3`)**, subdividing cleanly inside the fixed cage boundary without expanding the outer bounding box.
  - Changing or increasing U, V, or W purely adds interior control points within the model's fitted cage.
  - Eliminated duplicate lattices when tweaking parameters in the live redo / sidebar panel.

---

## What's New in v1.2.2

- 🎛️ **Default 2x2x2 Lattice Resolution (U=2, V=2, W=2)**:
  - Autolattice now defaults to an 8-corner bounding cube (`2x2x2`), providing the simplest, most intuitive control cage for quick shaping and organic deformation.
  - Columns (U), Rows (V), and Height (W) can still be interactively increased to any resolution via the Adjust Last Operation panel or N-Panel sidebar.

---

## What's New in v1.2.1

- 📐 **1.3x Model Circumference Scaling (1.3 Katı)**:
  - Autolattice now defaults to **1.3x (`1.30`)** of the model's dimensions, giving the exact sweet-spot clearance around the model's circumference/thickness without being unnecessarily huge.
  - Added an interactive **Size Ratio** slider (0.5x to 3.0x, default `1.30`) in both the Adjust Last Operation panel and N-Panel sidebar.
- 🎯 **Smart Edit-Mode Sub-Selection**:
  - In Edit Mode, selecting a subset of vertices (e.g. an arm, leg, or limb) fits the Autolattice **specifically to the selected limb + its skin radius** (scaled by 1.3x), preventing giant full-body cages when you just want to shape a single part!
  - If no sub-selection or in Object Mode, it seamlessly wraps the entire model.

---

## What's New in v1.2.0

- ⚡ **Renamed to "Autolattice"**:
  - Unified name for quick F3 search (`F3 > Autolattice`) and context menu access.
- 🎛️ **Real-Time Live Viewport Redo (Native Blender Operator Flow)**:
  - Just like native Blender primitives (Cube, Cylinder, Lattice), adding Autolattice immediately opens the **Adjust Last Operation** panel in the bottom-left corner of the 3D Viewport (or `F9`).
  - As you drag sliders for **Columns (U)**, **Rows (V)**, **Height (W)**, and **Margin**, the lattice cage and mesh deform **LIVE in real time** in the 3D Viewport!
- 📐 **Tight Oriented Bounding Box**:
  - The cage tightly wraps the evaluated mesh geometry (Skin, Subdivision, etc.) and aligns to the object's local rotation and orientation.
  - Safe clamp guarantees no singular matrix errors even on 2D planes or thin shapes.
- 🚀 **High-Performance NumPy Vectorization**:
  - Bounds extraction accelerated with NumPy buffer operations (`foreach_get`), keeping operations instant even on dense meshes.
- 🗂️ **Live Sidebar (N-Panel)**:
  - The **Auxlink** tab in the 3D Viewport Sidebar displays real-time resolution sliders and one-click buttons for Edit, Refit, Apply, and Remove.

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
