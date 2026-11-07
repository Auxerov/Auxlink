bl_info = {
    "name": "Auxlink",
    "author": "Auxerov",
    "version": (1, 2, 7),
    "blender": (5, 0, 0),
    "location": "3D Viewport > Right-Click > Auxlink  (also: Shift+A > Auxlink / Object menu / F3 / N-Panel)",
    "description": "Save and edit modifier stacks as presets, YAML import/export, and Autolattice deformation",
    "category": "Object",
}

import copy
import json
import math
import os
import re
import shutil

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper
import mathutils
from mathutils import Matrix, Vector


# =============================================================================
#  Minimal YAML (subset) reader / writer  -- no external dependencies
#  Supports: block mappings, block sequences, flow lists/maps (single line),
#  quoted/plain scalars, comments.
# =============================================================================
# --- YAML BEGIN ---

class YamlError(ValueError):
    pass


_INT_RE = re.compile(r"^[-+]?\d+$")
_FLOAT_RE = re.compile(r"^[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?$")
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _scan_quoted(s, start):
    """Return the index of the closing quote for the quoted token at `start`."""
    q = s[start]
    i = start + 1
    n = len(s)
    while i < n:
        c = s[i]
        if q == '"' and c == "\\":
            i += 2
            continue
        if c == q:
            if q == "'" and i + 1 < n and s[i + 1] == "'":
                i += 2
                continue
            return i
        i += 1
    raise YamlError("Unterminated quoted string: " + s)


def _decode_quoted(tok):
    if tok[0] == '"':
        try:
            return json.loads(tok)
        except ValueError as exc:
            raise YamlError("Invalid double-quoted string: %s (%s)" % (tok, exc))
    return tok[1:-1].replace("''", "'")


def _plain(tok):
    tok = tok.strip()
    if tok in ("", "~", "null", "Null", "NULL"):
        return None
    if tok in ("true", "True", "TRUE"):
        return True
    if tok in ("false", "False", "FALSE"):
        return False
    if _INT_RE.match(tok):
        return int(tok)
    if _FLOAT_RE.match(tok):
        return float(tok)
    if tok in (".inf", "+.inf", ".Inf", ".INF"):
        return math.inf
    if tok in ("-.inf", "-.Inf", "-.INF"):
        return -math.inf
    if tok in (".nan", ".NaN", ".NAN"):
        return math.nan
    return tok


def _skip_ws(s, i):
    while i < len(s) and s[i] == " ":
        i += 1
    return i


def _parse_flow(s, i=0):
    n = len(s)
    i = _skip_ws(s, i)
    if i >= n:
        raise YamlError("Unexpected end of flow value: " + s)
    c = s[i]
    if c == "[":
        items = []
        i += 1
        while True:
            i = _skip_ws(s, i)
            if i >= n:
                raise YamlError("Unterminated '[': " + s)
            if s[i] == "]":
                return items, i + 1
            value, i = _parse_flow(s, i)
            items.append(value)
            i = _skip_ws(s, i)
            if i < n and s[i] == ",":
                i += 1
            elif i < n and s[i] == "]":
                return items, i + 1
            else:
                raise YamlError("Expected ',' or ']' in: " + s)
    if c == "{":
        result = {}
        i += 1
        while True:
            i = _skip_ws(s, i)
            if i >= n:
                raise YamlError("Unterminated '{': " + s)
            if s[i] == "}":
                return result, i + 1
            if s[i] in "\"'":
                end = _scan_quoted(s, i)
                key = _decode_quoted(s[i:end + 1])
                i = end + 1
            else:
                j = s.find(":", i)
                if j == -1:
                    raise YamlError("Expected ':' in flow mapping: " + s)
                key = s[i:j].strip()
                i = j
            i = _skip_ws(s, i)
            if i >= n or s[i] != ":":
                raise YamlError("Expected ':' in flow mapping: " + s)
            value, i = _parse_flow(s, i + 1)
            result[key] = value
            i = _skip_ws(s, i)
            if i < n and s[i] == ",":
                i += 1
            elif i < n and s[i] == "}":
                return result, i + 1
            else:
                raise YamlError("Expected ',' or '}' in: " + s)
    if c in "\"'":
        end = _scan_quoted(s, i)
        return _decode_quoted(s[i:end + 1]), end + 1
    j = i
    while j < n and s[j] not in ",]}":
        j += 1
    return _plain(s[i:j]), j


def _parse_inline(text):
    if text[0] in "[{":
        value, i = _parse_flow(text, 0)
        if text[i:].strip():
            raise YamlError("Unexpected trailing text: " + text)
        return value
    if text[0] in "\"'":
        end = _scan_quoted(text, 0)
        if end != len(text) - 1:
            raise YamlError("Unexpected trailing text: " + text)
        return _decode_quoted(text)
    return _plain(text)


def _strip_comment(line):
    quote = None
    prev = ""
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if quote:
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                if quote == "'" and i + 1 < n and line[i + 1] == "'":
                    i += 2
                    continue
                quote = None
                prev = ch
        else:
            if ch in "\"'" and (prev == "" or prev in ":-[{,"):
                quote = ch
            elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
                return line[:i]
            if not ch.isspace():
                prev = ch
        i += 1
    return line


def _split_key(text):
    """'key: value' -> (key, 'value'); returns None if not a mapping entry."""
    if text[0] in "\"'":
        try:
            end = _scan_quoted(text, 0)
        except YamlError:
            return None
        rest = text[end + 1:]
        if rest.startswith(":") and (len(rest) == 1 or rest[1] == " "):
            return _decode_quoted(text[:end + 1]), rest[1:].strip()
        return None
    if text[0] in "[{":
        return None
    idx = text.find(": ")
    if idx == -1:
        if text.endswith(":"):
            idx = len(text) - 1
        else:
            return None
    return text[:idx].strip(), text[idx + 1:].strip()


class _Parser:
    def __init__(self, text):
        self.lines = []  # (indent, content, line_number)
        self.pos = 0
        if text.startswith("\ufeff"):
            text = text[1:]
        for number, raw in enumerate(text.splitlines(), 1):
            stripped = _strip_comment(raw).rstrip()
            if not stripped.strip():
                continue
            if stripped.strip() in ("---", "..."):
                continue
            lead = stripped[:len(stripped) - len(stripped.lstrip())]
            if "\t" in lead:
                raise YamlError("Line %d: tabs are not allowed for indentation" % number)
            self.lines.append((len(lead), stripped.strip(), number))

    def parse(self):
        if not self.lines:
            return None
        value = self._block(self.lines[0][0])
        if self.pos < len(self.lines):
            raise YamlError("Line %d: unexpected content" % self.lines[self.pos][2])
        return value

    def _block(self, indent):
        text = self.lines[self.pos][1]
        if text == "-" or text.startswith("- "):
            return self._seq(indent)
        return self._map(indent)

    def _seq(self, indent):
        result = []
        while self.pos < len(self.lines):
            ind, text, number = self.lines[self.pos]
            if ind != indent or not (text == "-" or text.startswith("- ")):
                break
            rest = text[1:].strip()
            if rest == "":
                self.pos += 1
                if self.pos < len(self.lines) and self.lines[self.pos][0] > indent:
                    result.append(self._block(self.lines[self.pos][0]))
                else:
                    result.append(None)
            elif _split_key(rest) is not None:
                offset = len(text) - len(text[1:].lstrip())
                self.lines[self.pos] = (indent + offset, rest, number)
                result.append(self._map(indent + offset))
            else:
                try:
                    result.append(_parse_inline(rest))
                except YamlError as exc:
                    raise YamlError("Line %d: %s" % (number, exc))
                self.pos += 1
        return result

    def _map(self, indent):
        result = {}
        while self.pos < len(self.lines):
            ind, text, number = self.lines[self.pos]
            if ind < indent:
                break
            if ind > indent:
                raise YamlError("Line %d: unexpected indentation" % number)
            if text == "-" or text.startswith("- "):
                raise YamlError("Line %d: unexpected list item inside a mapping" % number)
            kv = _split_key(text)
            if kv is None:
                raise YamlError("Line %d: expected 'key: value'" % number)
            key, rest = kv
            self.pos += 1
            if rest == "":
                if self.pos < len(self.lines) and self.lines[self.pos][0] > indent:
                    value = self._block(self.lines[self.pos][0])
                elif (self.pos < len(self.lines) and self.lines[self.pos][0] == indent
                      and (self.lines[self.pos][1] == "-" or self.lines[self.pos][1].startswith("- "))):
                    value = self._seq(indent)
                else:
                    value = None
            else:
                try:
                    value = _parse_inline(rest)
                except YamlError as exc:
                    raise YamlError("Line %d: %s" % (number, exc))
            result[key] = value
        return result


def parse_yaml(text):
    return _Parser(text).parse()


def _fmt_scalar(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v:
            return ".nan"
        if v == math.inf:
            return ".inf"
        if v == -math.inf:
            return "-.inf"
        r = repr(float("%.7g" % v))
        mantissa = r.split("e")[0]
        if "e" in r and "." not in mantissa:
            r = r.replace("e", ".0e")
        return r
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    raise TypeError("Cannot serialise %r" % type(v))


def _fmt_key(k):
    k = str(k)
    return k if _KEY_RE.match(k) else json.dumps(k, ensure_ascii=False)


def _flow(v):
    if isinstance(v, dict):
        return "{" + ", ".join("%s: %s" % (_fmt_key(k), _flow(x)) for k, x in v.items()) + "}"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_flow(x) for x in v) + "]"
    return _fmt_scalar(v)


def _has_dict(v):
    if isinstance(v, dict):
        return bool(v)
    if isinstance(v, (list, tuple)):
        return any(_has_dict(x) for x in v)
    return False


def _emit_map(d, indent, lines):
    pad = " " * indent
    for k, v in d.items():
        key = _fmt_key(k)
        if isinstance(v, dict) and v:
            lines.append("%s%s:" % (pad, key))
            _emit_map(v, indent + 2, lines)
        elif isinstance(v, (list, tuple)) and v and _has_dict(v):
            lines.append("%s%s:" % (pad, key))
            _emit_seq(v, indent + 2, lines)
        else:
            lines.append("%s%s: %s" % (pad, key, _flow(v)))


def _emit_seq(seq, indent, lines):
    pad = " " * indent
    for item in seq:
        if isinstance(item, dict) and item:
            sub = []
            _emit_map(item, indent + 2, sub)
            sub[0] = pad + "- " + sub[0][indent + 2:]
            lines.extend(sub)
        else:
            lines.append("%s- %s" % (pad, _flow(item)))


def dump_yaml(data, header=""):
    lines = ["# " + h for h in header.splitlines()] if header else []
    _emit_map(data, 0, lines)
    return "\n".join(lines) + "\n"

# --- YAML END ---


# =============================================================================
#  Modifier  <->  plain data
# =============================================================================

_SKIP = object()

# RNA properties that are never stored
SKIP_PROPS = {"rna_type", "type", "name", "is_override_data", "persistent_uid", "is_active"}

# Modifier types that carry simulation / cache state and can't be recreated from settings
UNSUPPORTED_TYPES = {
    "PARTICLE_SYSTEM", "FLUID", "CLOTH", "SOFT_BODY", "COLLISION", "DYNAMIC_PAINT",
}


def _to_plain(value):
    """Convert bpy arrays / nested arrays to python lists."""
    if isinstance(value, (str, bytes)):
        return value
    try:
        return [_to_plain(x) for x in value]
    except TypeError:
        return value


def _id_ref(idblock):
    return {"ref": idblock.bl_rna.identifier, "name": idblock.name}


def _resolve_id(ref, name):
    if not ref or not name:
        return None
    for prop in bpy.data.bl_rna.properties:
        if prop.type != 'COLLECTION':
            continue
        coll = getattr(bpy.data, prop.identifier, None)
        if coll is None or not hasattr(coll, "get"):
            continue
        try:
            item = coll.get(name)
        except Exception:
            continue
        if isinstance(item, bpy.types.ID) and item.bl_rna.identifier == ref:
            return item
    return None


def _serialize_value(prop, value):
    t = prop.type
    if t == 'POINTER':
        if value is None:
            return None
        if isinstance(value, bpy.types.ID):
            return _id_ref(value)
        return _SKIP
    if t == 'COLLECTION':
        return _SKIP
    if t == 'ENUM':
        return sorted(value) if prop.is_enum_flag else value
    if t in {'FLOAT', 'INT', 'BOOLEAN'}:
        if getattr(prop, "is_array", False) or getattr(prop, "array_length", 0) > 0:
            return _to_plain(value)
        return value
    if t == 'STRING':
        return value
    return _SKIP


def _deserialize_value(prop, data):
    t = prop.type
    if t == 'POINTER':
        if data is None:
            return None
        if isinstance(data, dict):
            item = _resolve_id(data.get("ref"), data.get("name"))
            if item is None:
                raise LookupError("%s '%s' not found in this file" % (data.get("ref"), data.get("name")))
            return item
        raise ValueError("expected a reference")
    if t == 'ENUM' and prop.is_enum_flag:
        return set(data)
    return data


def _idprop_to_plain(value):
    if isinstance(value, bpy.types.ID):
        return _id_ref(value)
    if isinstance(value, (bool, int, float, str)):
        return value
    if hasattr(value, "to_list"):
        return value.to_list()
    return _SKIP


def serialize_modifier(mod):
    props = {}
    for prop in mod.bl_rna.properties:
        pid = prop.identifier
        if pid in SKIP_PROPS or prop.is_readonly:
            continue
        try:
            value = getattr(mod, pid)
        except Exception:
            continue
        data = _serialize_value(prop, value)
        if data is not _SKIP:
            props[pid] = data

    custom = {}
    try:
        keys = list(mod.keys())
    except (TypeError, AttributeError):
        keys = []
    for key in keys:
        if key.startswith("_RNA_UI"):
            continue
        try:
            data = _idprop_to_plain(mod[key])
        except Exception:
            continue
        if data is not _SKIP:
            custom[key] = data

    return {"name": mod.name, "type": mod.type, "properties": props, "custom_properties": custom}


def collect_modifiers(obj, only_active=False):
    if only_active and obj.modifiers.active is not None:
        mods = [obj.modifiers.active]
    else:
        mods = list(obj.modifiers)
    return [m for m in mods if m.type not in UNSUPPORTED_TYPES], \
           [m for m in mods if m.type in UNSUPPORTED_TYPES]


def apply_modifier_data(obj, md, warnings):
    """Create one modifier on `obj` from stored data. Returns the modifier or None."""
    mtype = md["type"]
    try:
        mod = obj.modifiers.new(name=md.get("name") or mtype.title(), type=mtype)
    except (TypeError, RuntimeError, ValueError) as exc:
        warnings.append("%s: cannot add '%s' (%s)" % (obj.name, mtype, exc))
        return None

    props = md.get("properties") or {}
    for key in sorted(props, key=lambda k: k != "node_group"):
        prop = mod.bl_rna.properties.get(key)
        if prop is None or prop.is_readonly:
            continue
        try:
            setattr(mod, key, _deserialize_value(prop, props[key]))
        except Exception as exc:
            warnings.append("%s/%s: '%s' not applied (%s)" % (obj.name, mod.name, key, exc))

    custom = md.get("custom_properties") or {}
    if custom and not (mod.type == 'NODES' and getattr(mod, "node_group", None) is None):
        for key, value in custom.items():
            try:
                if isinstance(value, dict):
                    item = _resolve_id(value.get("ref"), value.get("name"))
                    if item is None:
                        raise LookupError("%s '%s' not found" % (value.get("ref"), value.get("name")))
                    value = item
                mod[key] = value
            except Exception as exc:
                warnings.append("%s/%s: input '%s' not applied (%s)" % (obj.name, mod.name, key, exc))
    return mod


# =============================================================================
#  Preset storage
# =============================================================================

def presets_from_document(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("presets"), list):
        raise ValueError("File has no 'presets' list")
    result = {}
    for idx, p in enumerate(doc["presets"], 1):
        if not isinstance(p, dict) or p.get("name") in (None, ""):
            raise ValueError("Preset #%d has no name" % idx)
        name = str(p["name"]).strip()
        mods = p.get("modifiers") or []
        if not isinstance(mods, list):
            raise ValueError("Preset '%s': 'modifiers' must be a list" % name)
        clean = []
        for m in mods:
            if not isinstance(m, dict) or not isinstance(m.get("type"), str):
                raise ValueError("Preset '%s': every modifier needs a 'type'" % name)
            props = m.get("properties") or {}
            custom = m.get("custom_properties") or {}
            if not isinstance(props, dict) or not isinstance(custom, dict):
                raise ValueError("Preset '%s': 'properties' must be a mapping" % name)
            clean.append({
                "name": str(m.get("name") or m["type"].title()),
                "type": m["type"],
                "properties": props,
                "custom_properties": custom,
            })
        result[name] = {"modifiers": clean}
    return result


def presets_to_document(presets):
    return {
        "auxlink_version": 1,
        "presets": [{"name": n, "modifiers": d["modifiers"]} for n, d in presets.items()],
    }


YAML_HEADER = "Auxlink modifier presets\nGenerated by Auxlink (author: Auxerov)"


class _Store:
    def __init__(self):
        self.presets = {}

    @property
    def directory(self):
        return bpy.utils.user_resource('CONFIG', path="auxlink", create=True)

    @property
    def path(self):
        return os.path.join(self.directory, "presets.yaml")

    @property
    def default_path(self):
        addon_dir = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.join(addon_dir, "default_presets.yaml")
        if os.path.isfile(cand):
            return cand
        return ""

    def load(self):
        self.presets = {}
        path = self.path
        if not os.path.isfile(path):
            def_path = self.default_path
            if def_path and os.path.isfile(def_path):
                try:
                    with open(def_path, "r", encoding="utf-8") as f:
                        self.presets = presets_from_document(parse_yaml(f.read()))
                    self.save()
                    return
                except Exception as exc:
                    print("[Auxlink] Could not read default presets: %s" % exc)
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                self.presets = presets_from_document(parse_yaml(f.read()))
        except Exception as exc:
            print("[Auxlink] Could not read %s: %s" % (path, exc))
            try:
                shutil.copy(path, path + ".bak")
            except OSError:
                pass

    def save(self):
        path = self.path
        tmp = path + ".tmp"
        content = dump_yaml(presets_to_document(self.presets), YAML_HEADER)
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)

        def_path = self.default_path
        if def_path and os.path.isfile(def_path):
            try:
                with open(def_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(content)
            except Exception:
                pass


store = _Store()


def _redraw_all():
    wm = bpy.context.window_manager
    if wm is None:
        return
    for window in wm.windows:
        screen = window.screen
        if screen:
            for area in screen.areas:
                area.tag_redraw()


def get_preferences(context=None):
    if context is None:
        context = bpy.context
    addon_name = __package__ or __name__
    prefs = context.preferences.addons.get(addon_name)
    if prefs:
        return prefs.preferences
    for name, addon in context.preferences.addons.items():
        if name == "auxlink" or name.endswith(".auxlink") or name == addon_name:
            if addon.preferences:
                return addon.preferences
    return None


# =============================================================================
#  Preset Operators
# =============================================================================

class AUXLINK_OT_save_preset(bpy.types.Operator):
    bl_idname = "auxlink.save_preset"
    bl_label = "Save Modifier Preset"
    bl_description = "Save the modifier stack of the active object as an Auxlink preset"
    bl_options = {'REGISTER', 'INTERNAL'}

    preset_name: StringProperty(name="Preset Name", default="", options={'SKIP_SAVE'})
    only_active: BoolProperty(
        name="Active Modifier Only",
        description="Save only the active modifier instead of the whole stack",
        default=False,
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj is None:
            cls.poll_message_set("No active object")
            return False
        if len(obj.modifiers) == 0:
            cls.poll_message_set("The active object has no modifiers")
            return False
        return True

    def invoke(self, context, event):
        self.preset_name = ""
        return context.window_manager.invoke_props_dialog(
            self, width=340, title="Save Modifier Preset", confirm_text="Save")

    def draw(self, context):
        layout = self.layout
        obj = context.active_object
        layout.prop(self, "preset_name", text="Name")
        if len(obj.modifiers) > 1:
            layout.prop(self, "only_active")
        usable, _skipped = collect_modifiers(obj, self.only_active)
        layout.label(text="%d modifier(s) will be saved" % len(usable), icon='INFO')
        if self.preset_name.strip() in store.presets:
            layout.label(text="A preset with this name exists and will be replaced", icon='ERROR')

    def execute(self, context):
        name = self.preset_name.strip()
        if not name:
            self.report({'ERROR'}, "Please enter a preset name")
            return {'CANCELLED'}
        obj = context.active_object
        usable, skipped = collect_modifiers(obj, self.only_active)
        if not usable:
            self.report({'ERROR'}, "Nothing to save")
            return {'CANCELLED'}

        store.presets[name] = {"modifiers": [serialize_modifier(m) for m in usable]}
        try:
            store.save()
        except OSError as exc:
            self.report({'ERROR'}, "Could not write presets file: %s" % exc)
            return {'CANCELLED'}

        msg = "Saved preset '%s' (%d modifier(s))" % (name, len(usable))
        if skipped:
            msg += " - skipped unsupported: " + ", ".join(m.name for m in skipped)
        self.report({'INFO'}, msg)
        _redraw_all()
        return {'FINISHED'}


class AUXLINK_OT_add_preset(bpy.types.Operator):
    bl_idname = "auxlink.add_preset"
    bl_label = "Add Modifier Preset"
    bl_description = "Add a saved Auxlink modifier preset to the selected objects"
    bl_options = {'REGISTER', 'UNDO'}

    preset_name: StringProperty(name="Preset", default="", options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def description(cls, context, properties):
        preset = store.presets.get(properties.preset_name)
        if preset:
            names = ", ".join(m["name"] for m in preset["modifiers"][:6])
            if len(preset["modifiers"]) > 6:
                names += ", ..."
            return "Add preset '%s' to the selected objects (%s)" % (properties.preset_name, names)
        return cls.bl_description

    @classmethod
    def poll(cls, context):
        if context.selected_objects or context.active_object:
            return True
        cls.poll_message_set("No object selected")
        return False

    def execute(self, context):
        preset = store.presets.get(self.preset_name)
        if preset is None:
            self.report({'ERROR'}, "Preset '%s' not found" % self.preset_name)
            return {'CANCELLED'}

        targets = list(context.selected_objects) or [context.active_object]
        warnings = []
        created = 0
        for obj in targets:
            if obj is None:
                continue
            for md in preset["modifiers"]:
                if apply_modifier_data(obj, md, warnings) is not None:
                    created += 1
            obj.update_tag()

        for w in warnings:
            print("[Auxlink] " + w)
        if warnings:
            shown = "; ".join(warnings[:3]) + (" ..." if len(warnings) > 3 else "")
            self.report({'WARNING'}, "Added %d modifier(s) with issues: %s" % (created, shown))
        else:
            self.report({'INFO'}, "Added '%s' (%d modifier(s))" % (self.preset_name, created))
        _redraw_all()
        return {'FINISHED'} if created else {'CANCELLED'}


class AUXLINK_OT_delete_preset(bpy.types.Operator):
    bl_idname = "auxlink.delete_preset"
    bl_label = "Delete Preset"
    bl_description = "Delete this Auxlink preset"
    bl_options = {'INTERNAL'}

    preset_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(
            self, width=320, title="Delete Preset", confirm_text="Delete")

    def draw(self, context):
        self.layout.label(text="Delete preset '%s'?" % self.preset_name, icon='QUESTION')

    def execute(self, context):
        if self.preset_name in store.presets:
            del store.presets[self.preset_name]
            try:
                store.save()
            except OSError as exc:
                self.report({'ERROR'}, "Could not write presets file: %s" % exc)
                return {'CANCELLED'}
            prefs = get_preferences(context)
            if prefs and prefs.active_preset == self.preset_name:
                prefs.active_preset = ""
            self.report({'INFO'}, "Deleted preset '%s'" % self.preset_name)
        _redraw_all()
        return {'FINISHED'}


class AUXLINK_OT_rename_preset(bpy.types.Operator):
    bl_idname = "auxlink.rename_preset"
    bl_label = "Rename Preset"
    bl_description = "Rename this preset"
    bl_options = {'INTERNAL'}

    old_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    new_name: StringProperty(name="New Name", default="", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        self.new_name = self.old_name
        return context.window_manager.invoke_props_dialog(
            self, width=320, title="Rename Preset", confirm_text="Rename")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "new_name", text="Name")
        clean = self.new_name.strip()
        if clean in store.presets and clean != self.old_name:
            layout.label(text="A preset with this name already exists!", icon='ERROR')

    def execute(self, context):
        clean = self.new_name.strip()
        if not clean:
            self.report({'ERROR'}, "Preset name cannot be empty")
            return {'CANCELLED'}
        if clean == self.old_name:
            return {'FINISHED'}
        if clean in store.presets:
            self.report({'ERROR'}, f"Preset '{clean}' already exists")
            return {'CANCELLED'}
        if self.old_name not in store.presets:
            self.report({'ERROR'}, f"Preset '{self.old_name}' not found")
            return {'CANCELLED'}

        new_presets = {}
        for k, v in store.presets.items():
            if k == self.old_name:
                new_presets[clean] = v
            else:
                new_presets[k] = v
        store.presets = new_presets
        store.save()

        prefs = get_preferences(context)
        if prefs and prefs.active_preset == self.old_name:
            prefs.active_preset = clean

        self.report({'INFO'}, f"Renamed '{self.old_name}' to '{clean}'")
        _redraw_all()
        return {'FINISHED'}


class AUXLINK_OT_duplicate_preset(bpy.types.Operator):
    bl_idname = "auxlink.duplicate_preset"
    bl_label = "Duplicate Preset"
    bl_description = "Create a copy of this preset"
    bl_options = {'INTERNAL'}

    preset_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        if self.preset_name not in store.presets:
            self.report({'ERROR'}, "Preset not found")
            return {'CANCELLED'}

        base_name = self.preset_name + " Copy"
        new_name = base_name
        counter = 2
        while new_name in store.presets:
            new_name = f"{base_name} {counter}"
            counter += 1

        store.presets[new_name] = copy.deepcopy(store.presets[self.preset_name])
        store.save()

        prefs = get_preferences(context)
        if prefs:
            prefs.active_preset = new_name

        self.report({'INFO'}, f"Duplicated preset as '{new_name}'")
        _redraw_all()
        return {'FINISHED'}


class AUXLINK_OT_select_preset_for_edit(bpy.types.Operator):
    bl_idname = "auxlink.select_preset_for_edit"
    bl_label = "Edit Preset"
    bl_description = "Inspect and edit this preset's modifiers"
    bl_options = {'INTERNAL'}

    preset_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        prefs = get_preferences(context)
        if prefs:
            if prefs.active_preset == self.preset_name:
                prefs.active_preset = ""
            else:
                prefs.active_preset = self.preset_name
        _redraw_all()
        return {'FINISHED'}


class AUXLINK_OT_move_preset_modifier(bpy.types.Operator):
    bl_idname = "auxlink.move_preset_modifier"
    bl_label = "Move Modifier"
    bl_description = "Move this modifier up or down inside the preset stack"
    bl_options = {'INTERNAL'}

    preset_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    mod_index: IntProperty(options={'SKIP_SAVE', 'HIDDEN'})
    direction: EnumProperty(
        items=[('UP', "Up", ""), ('DOWN', "Down", "")],
        options={'SKIP_SAVE', 'HIDDEN'}
    )

    def execute(self, context):
        preset = store.presets.get(self.preset_name)
        if not preset:
            return {'CANCELLED'}
        mods = preset.get("modifiers", [])
        idx = self.mod_index
        if self.direction == 'UP' and idx > 0:
            mods[idx], mods[idx - 1] = mods[idx - 1], mods[idx]
        elif self.direction == 'DOWN' and idx < len(mods) - 1:
            mods[idx], mods[idx + 1] = mods[idx + 1], mods[idx]
        else:
            return {'CANCELLED'}

        store.save()
        _redraw_all()
        return {'FINISHED'}


class AUXLINK_OT_remove_preset_modifier(bpy.types.Operator):
    bl_idname = "auxlink.remove_preset_modifier"
    bl_label = "Remove Modifier from Preset"
    bl_description = "Remove this modifier from the preset"
    bl_options = {'INTERNAL'}

    preset_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    mod_index: IntProperty(options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        preset = store.presets.get(self.preset_name)
        if not preset:
            return {'CANCELLED'}
        mods = preset.get("modifiers", [])
        if 0 <= self.mod_index < len(mods):
            removed = mods.pop(self.mod_index)
            store.save()
            self.report({'INFO'}, f"Removed modifier '{removed.get('name')}' from preset")
            _redraw_all()
            return {'FINISHED'}
        return {'CANCELLED'}


class AUXLINK_OT_rename_preset_modifier(bpy.types.Operator):
    bl_idname = "auxlink.rename_preset_modifier"
    bl_label = "Rename Modifier"
    bl_description = "Rename this modifier inside the preset"
    bl_options = {'INTERNAL'}

    preset_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})
    mod_index: IntProperty(options={'SKIP_SAVE', 'HIDDEN'})
    new_name: StringProperty(name="Modifier Name", default="", options={'SKIP_SAVE'})

    def invoke(self, context, event):
        preset = store.presets.get(self.preset_name)
        if preset and 0 <= self.mod_index < len(preset.get("modifiers", [])):
            self.new_name = preset["modifiers"][self.mod_index].get("name", "")
        return context.window_manager.invoke_props_dialog(
            self, width=300, title="Rename Modifier", confirm_text="OK")

    def draw(self, context):
        self.layout.prop(self, "new_name", text="Name")

    def execute(self, context):
        clean = self.new_name.strip()
        if not clean:
            self.report({'ERROR'}, "Name cannot be empty")
            return {'CANCELLED'}
        preset = store.presets.get(self.preset_name)
        if not preset:
            return {'CANCELLED'}
        mods = preset.get("modifiers", [])
        if 0 <= self.mod_index < len(mods):
            mods[self.mod_index]["name"] = clean
            store.save()
            _redraw_all()
            return {'FINISHED'}
        return {'CANCELLED'}


class AUXLINK_OT_update_preset_from_active(bpy.types.Operator):
    bl_idname = "auxlink.update_preset_from_active"
    bl_label = "Update from Active Object"
    bl_description = "Overwrite this preset with the modifier stack of the currently active object"
    bl_options = {'INTERNAL'}

    preset_name: StringProperty(options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return context.active_object is not None and len(context.active_object.modifiers) > 0

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(
            self, width=340, title="Update Preset", confirm_text="Overwrite")

    def draw(self, context):
        obj = context.active_object
        usable, _ = collect_modifiers(obj, False)
        layout = self.layout
        layout.label(text=f"Replace '{self.preset_name}' with {len(usable)} modifier(s)", icon='QUESTION')
        layout.label(text=f"Source: {obj.name}", icon='OBJECT_DATA')

    def execute(self, context):
        obj = context.active_object
        usable, skipped = collect_modifiers(obj, False)
        if not usable:
            self.report({'ERROR'}, "No usable modifiers on active object")
            return {'CANCELLED'}

        store.presets[self.preset_name] = {"modifiers": [serialize_modifier(m) for m in usable]}
        store.save()
        self.report({'INFO'}, f"Updated preset '{self.preset_name}' ({len(usable)} modifier(s))")
        _redraw_all()
        return {'FINISHED'}


class AUXLINK_OT_restore_defaults(bpy.types.Operator):
    bl_idname = "auxlink.restore_defaults"
    bl_label = "Restore Default Presets"
    bl_description = "Reload factory default presets shipped with Auxlink"
    bl_options = {'INTERNAL'}

    mode: EnumProperty(
        name="Restore Mode",
        items=[
            ('MERGE', "Merge (Keep Existing)", "Add default presets while keeping your own custom presets"),
            ('REPLACE_ALL', "Reset All", "Remove all current presets and restore only factory defaults"),
        ],
        default='MERGE',
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(
            self, width=340, title="Restore Default Presets", confirm_text="Restore")

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "mode", expand=True)

    def execute(self, context):
        def_path = store.default_path
        if not def_path or not os.path.isfile(def_path):
            self.report({'ERROR'}, "Default presets file not found")
            return {'CANCELLED'}

        try:
            with open(def_path, "r", encoding="utf-8") as f:
                defaults = presets_from_document(parse_yaml(f.read()))
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to read defaults: {exc}")
            return {'CANCELLED'}

        if self.mode == 'REPLACE_ALL':
            store.presets = defaults
            imported = len(defaults)
        else:
            imported = 0
            for k, v in defaults.items():
                if k not in store.presets:
                    store.presets[k] = v
                    imported += 1

        store.save()
        self.report({'INFO'}, f"Restored default presets ({imported} added)")
        _redraw_all()
        return {'FINISHED'}


class AUXLINK_OT_open_presets_file(bpy.types.Operator):
    bl_idname = "auxlink.open_presets_file"
    bl_label = "Edit in Text Editor"
    bl_description = "Open the presets.yaml file in the system default text editor"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        if not os.path.isfile(store.path):
            store.save()
        bpy.ops.wm.path_open(filepath=store.path)
        return {'FINISHED'}


class AUXLINK_OT_reload_presets(bpy.types.Operator):
    bl_idname = "auxlink.reload_presets"
    bl_label = "Reload Presets"
    bl_description = "Re-read the presets file from disk"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        store.load()
        self.report({'INFO'}, "Loaded %d preset(s)" % len(store.presets))
        _redraw_all()
        return {'FINISHED'}


class AUXLINK_OT_export_presets(bpy.types.Operator, ExportHelper):
    bl_idname = "auxlink.export_presets"
    bl_label = "Export Presets (YAML)"
    bl_description = "Export all Auxlink presets to a YAML file"
    bl_options = {'INTERNAL'}

    filename_ext = ".yaml"
    filter_glob: StringProperty(default="*.yaml;*.yml", options={'HIDDEN'})

    @classmethod
    def poll(cls, context):
        return bool(store.presets)

    def invoke(self, context, event):
        self.filepath = "auxlink_presets.yaml"
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            with open(self.filepath, "w", encoding="utf-8", newline="\n") as f:
                f.write(dump_yaml(presets_to_document(store.presets), YAML_HEADER))
        except OSError as exc:
            self.report({'ERROR'}, "Export failed: %s" % exc)
            return {'CANCELLED'}
        self.report({'INFO'}, "Exported %d preset(s)" % len(store.presets))
        return {'FINISHED'}


class AUXLINK_OT_import_presets(bpy.types.Operator, ImportHelper):
    bl_idname = "auxlink.import_presets"
    bl_label = "Import Presets (YAML)"
    bl_description = "Import Auxlink presets from a YAML file"
    bl_options = {'INTERNAL'}

    filename_ext = ".yaml"
    filter_glob: StringProperty(default="*.yaml;*.yml", options={'HIDDEN'})
    mode: EnumProperty(
        name="If Name Exists",
        items=[
            ('OVERWRITE', "Overwrite", "Replace presets that have the same name"),
            ('SKIP', "Skip", "Keep the existing preset and ignore the imported one"),
            ('REPLACE_ALL', "Replace All", "Remove all current presets and use only the imported ones"),
        ],
        default='OVERWRITE',
    )

    def execute(self, context):
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                incoming = presets_from_document(parse_yaml(f.read()))
        except (OSError, ValueError) as exc:
            self.report({'ERROR'}, "Import failed: %s" % exc)
            return {'CANCELLED'}

        if self.mode == 'REPLACE_ALL':
            store.presets = {}
        imported = skipped = 0
        for name, data in incoming.items():
            if name in store.presets and self.mode == 'SKIP':
                skipped += 1
                continue
            store.presets[name] = data
            imported += 1
        try:
            store.save()
        except OSError as exc:
            self.report({'ERROR'}, "Could not write presets file: %s" % exc)
            return {'CANCELLED'}
        self.report({'INFO'}, "Imported %d preset(s), skipped %d" % (imported, skipped))
        _redraw_all()
        return {'FINISHED'}


# =============================================================================
#  Autolattice Helpers & Operators
# =============================================================================
import bpy
import bmesh
from mathutils import Vector, Matrix
from bpy.props import IntProperty, FloatProperty, EnumProperty, BoolProperty

AUTOLATTICE_FACTOR = 1.3


def _find_lattice_pair(context):
    """Return (mesh_obj, lattice_mod, lattice_obj) from active object."""
    act = context.active_object
    if not act:
        return None, None, None

    if act.type == 'MESH':
        for m in reversed(act.modifiers):
            if m.type == 'LATTICE' and m.object:
                return act, m, m.object
        return None, None, None

    if act.type == 'LATTICE':
        if act.parent and act.parent.type == 'MESH':
            for m in act.parent.modifiers:
                if m.type == 'LATTICE' and m.object == act:
                    return act.parent, m, act
        for obj in context.scene.objects:
            if obj.type == 'MESH':
                for m in obj.modifiers:
                    if m.type == 'LATTICE' and m.object == act:
                        return obj, m, act
        return None, None, act

    return None, None, None


def _resolve_target_mesh(context):
    """Mesh the operator should work on (active mesh or owner of active lattice)."""
    act = context.active_object
    if not act:
        return None
    if act.type == 'MESH':
        return act
    if act.type == 'LATTICE':
        mesh_obj, _mod, _lat = _find_lattice_pair(context)
        return mesh_obj
    return None


def _calc_subselection_bounds(obj):
    """Bounds of selected verts (Edit mode only). (None, None) if all/none selected."""
    if not obj or obj.type != 'MESH' or obj.mode != 'EDIT':
        return None, None

    has_skin = any(m.type == 'SKIN' for m in obj.modifiers)
    pts = []
    try:
        bm = bmesh.from_edit_mesh(obj.data)
        total = len(bm.verts)
        skin_layer = None
        if has_skin and bm.verts.layers.skin:
            skin_layer = bm.verts.layers.skin.active
        for v in bm.verts:
            if not v.select:
                continue
            rx = ry = 0.0
            if skin_layer is not None:
                try:
                    r = v[skin_layer].radius
                    rx, ry = float(r[0]), float(r[1])
                except Exception:
                    pass
            pts.append((Vector(v.co), rx, ry))
    except Exception:
        return None, None

    if not pts or len(pts) >= total:
        return None, None

    mn = Vector((float('inf'),) * 3)
    mx = Vector((float('-inf'),) * 3)
    for co, rx, ry in pts:
        rz = max(rx, ry)
        mn.x = min(mn.x, co.x - rx)
        mn.y = min(mn.y, co.y - ry)
        mn.z = min(mn.z, co.z - rz)
        mx.x = max(mx.x, co.x + rx)
        mx.y = max(mx.y, co.y + ry)
        mx.z = max(mx.z, co.z + rz)
    return mn, mx


def _calc_mesh_bounds_tight(obj, context):
    """Local bbox of the evaluated mesh, ignoring any AutoLattice modifier."""
    disabled = []
    for m in obj.modifiers:
        if m.type == 'LATTICE' and m.name.startswith("AutoLattice") and m.show_viewport:
            m.show_viewport = False
            disabled.append(m)
    try:
        context.view_layer.update()
        eval_obj = obj.evaluated_get(context.evaluated_depsgraph_get())
        corners = [Vector(c) for c in eval_obj.bound_box] if eval_obj.bound_box else []
        if corners:
            mn = Vector([min(c[i] for c in corners) for i in range(3)])
            mx = Vector([max(c[i] for c in corners) for i in range(3)])
        else:
            mn = Vector((-1.0, -1.0, -1.0))
            mx = Vector((1.0, 1.0, 1.0))
        return mn, mx
    finally:
        for m in disabled:
            m.show_viewport = True
        context.view_layer.update()


def _get_bounds(obj, context, allow_subselection=True):
    """Returns (center, size) in the mesh's local space."""
    mn = mx = None
    if allow_subselection:
        mn, mx = _calc_subselection_bounds(obj)
    if mn is None or mx is None:
        mn, mx = _calc_mesh_bounds_tight(obj, context)
    return (mn + mx) / 2.0, (mx - mn)


def _padded_size(size_local, factor):
    """size * factor, with a per-axis minimum so flat/2D meshes never collapse."""
    max_dim = max(size_local)
    if max_dim < 1e-6:
        max_dim = 1.0
    min_thick = max(max_dim * 0.1, 0.05)
    return Vector([max(size_local[i] * factor, min_thick) for i in range(3)])


def _apply_cage_transform(lat_obj, mesh_obj, center, padded):
    if lat_obj.parent == mesh_obj:
        lat_obj.location = center
        lat_obj.rotation_euler = (0.0, 0.0, 0.0)
        lat_obj.scale = padded
    else:
        lat_obj.matrix_world = (
            mesh_obj.matrix_world
            @ Matrix.Translation(center)
            @ Matrix.Diagonal(padded.to_4d())
        )


def _remove_lattice_object(lat_obj):
    if not lat_obj:
        return
    lat_data = lat_obj.data
    try:
        bpy.data.objects.remove(lat_obj, do_unlink=True)
    except Exception:
        pass
    try:
        if lat_data and lat_data.users == 0:
            bpy.data.lattices.remove(lat_data, do_unlink=True)
    except Exception:
        pass


def _cleanup_old_autolattice(obj):
    """Remove old AutoLattice modifiers + their objects + orphan leftovers."""
    for m in list(obj.modifiers):
        if m.type == 'LATTICE' and m.name.startswith("AutoLattice"):
            old = m.object
            obj.modifiers.remove(m)
            _remove_lattice_object(old)

    # Ghost lattices left over from broken runs (parented to this mesh, no modifier uses them)
    used = {m.object for m in obj.modifiers if m.type == 'LATTICE' and m.object}
    for o in list(bpy.data.objects):
        if (o.type == 'LATTICE' and o.parent == obj
                and "auxlink_base_size" in o.keys() and o not in used):
            _remove_lattice_object(o)


def _safe_collection(obj, context):
    """A collection that is actually visible in the view layer."""
    def find_lc(lc, col):
        if lc.collection == col:
            return lc
        for ch in lc.children:
            r = find_lc(ch, col)
            if r:
                return r
        return None

    for col in obj.users_collection:
        lc = find_lc(context.view_layer.layer_collection, col)
        if lc and not lc.exclude:
            return col
    return context.scene.collection


def _set_lattice_resolution(lat_obj, u, v, w):
    """Change U/V/W while keeping the cage transform (bounds) perfectly locked."""
    saved_basis = lat_obj.matrix_basis.copy()
    saved_parent_inv = lat_obj.matrix_parent_inverse.copy()
    lat_data = lat_obj.data
    lat_data.points_u = u
    lat_data.points_v = v
    lat_data.points_w = w
    lat_obj.matrix_parent_inverse = saved_parent_inv
    lat_obj.matrix_basis = saved_basis


class AUXLINK_OT_autolattice(bpy.types.Operator):
    bl_idname = "auxlink.autolattice"
    bl_label = "Autolattice"
    bl_description = "Create a standard 2x2x2 lattice fitted 1.3x around the mesh"
    bl_options = {'REGISTER', 'UNDO'}

    points_u: IntProperty(name="Columns (U / X)", default=2, min=1, max=64)
    points_v: IntProperty(name="Rows (V / Y)", default=2, min=1, max=64)
    points_w: IntProperty(name="Height (W / Z)", default=2, min=1, max=64)
    scale_factor: FloatProperty(
        name="Size Ratio", default=AUTOLATTICE_FACTOR, min=0.5, max=5.0, precision=2
    )
    interpolation: EnumProperty(
        name="Interpolation",
        items=[
            ('KEY_BSPLINE', "B-Spline", "Smooth B-Spline curves"),
            ('KEY_LINEAR', "Linear", "Linear"),
            ('KEY_CARDINAL', "Cardinal", "Cardinal"),
            ('KEY_CATMULL_ROM', "Catmull-Rom", "Catmull-Rom"),
        ],
        default='KEY_BSPLINE',
    )
    placement: EnumProperty(
        name="Stack Position",
        items=[
            ('AFTER_SKIN', "After Skin", "Right after the Skin modifier"),
            ('END', "Bottom of Stack", "Bottom of the modifier stack"),
            ('TOP', "Top of Stack", "Top of the modifier stack"),
        ],
        default='AFTER_SKIN',
    )
    use_parent: BoolProperty(name="Parent to Mesh", default=True)
    enter_edit_mode: BoolProperty(name="Enter Edit Mode", default=True)

    @classmethod
    def poll(cls, context):
        return _resolve_target_mesh(context) is not None

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False

        col = layout.column(align=True)
        col.label(text="Grid Resolution", icon='GRID')
        col.prop(self, "points_u")
        col.prop(self, "points_v")
        col.prop(self, "points_w")

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Fit & Placement", icon='MOD_LATTICE')
        col.prop(self, "scale_factor")
        col.prop(self, "interpolation")
        col.prop(self, "placement")

        layout.separator()
        col = layout.column(align=True)
        col.prop(self, "use_parent")
        col.prop(self, "enter_edit_mode")

    def execute(self, context):
        obj = _resolve_target_mesh(context)
        if obj is None:
            self.report({'ERROR'}, "Active object must be a Mesh or an Autolattice")
            return {'CANCELLED'}

        # Sub-selection bounds are only valid if the MESH is in Edit mode
        sub_min = sub_max = None
        if obj.mode == 'EDIT':
            sub_min, sub_max = _calc_subselection_bounds(obj)
            bpy.ops.object.mode_set(mode='OBJECT')
        elif context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

        # Always start clean: no ghost modifier / lattice objects
        _cleanup_old_autolattice(obj)

        if sub_min is not None and sub_max is not None:
            center = (sub_min + sub_max) / 2.0
            size = sub_max - sub_min
        else:
            center, size = _get_bounds(obj, context, allow_subselection=False)

        padded = _padded_size(size, self.scale_factor)

        lat_name = f"{obj.name}_Lattice"
        lat_data = bpy.data.lattices.new(name=lat_name)
        lat_data.points_u = self.points_u
        lat_data.points_v = self.points_v
        lat_data.points_w = self.points_w
        lat_data.interpolation_type_u = self.interpolation
        lat_data.interpolation_type_v = self.interpolation
        lat_data.interpolation_type_w = self.interpolation

        lat_obj = bpy.data.objects.new(name=lat_name, object_data=lat_data)
        lat_obj.show_in_front = True
        lat_obj.hide_viewport = False
        lat_obj.hide_render = True
        lat_obj["auxlink_base_size"] = list(size)
        lat_obj["auxlink_center"] = list(center)

        _safe_collection(obj, context).objects.link(lat_obj)

        if self.use_parent:
            lat_obj.parent = obj
        _apply_cage_transform(lat_obj, obj, center, padded)

        lat_mod = obj.modifiers.new(name="AutoLattice", type='LATTICE')
        lat_mod.object = lat_obj

        # Modifier stack position (no bpy.ops needed)
        count = len(obj.modifiers)
        cur = count - 1
        target = cur
        if self.placement == 'AFTER_SKIN':
            skin_idx = -1
            for i, m in enumerate(obj.modifiers):
                if m.type == 'SKIN':
                    skin_idx = i
            if skin_idx != -1:
                target = skin_idx + 1
        elif self.placement == 'TOP':
            target = 0
        target = max(0, min(target, count - 1))
        if target != cur:
            try:
                obj.modifiers.move(cur, target)
            except Exception:
                pass

        # Select all lattice points so the 8 corners are highlighted
        try:
            for p in lat_data.points:
                p.select = True
        except Exception:
            pass

        context.view_layer.update()

        for o in context.selected_objects:
            o.select_set(False)
        context.view_layer.objects.active = lat_obj
        lat_obj.select_set(True)

        if self.enter_edit_mode:
            try:
                bpy.ops.object.mode_set(mode='EDIT')
            except Exception:
                pass

        self.report(
            {'INFO'},
            f"Autolattice: {self.points_u}x{self.points_v}x{self.points_w} @ {self.scale_factor:.2f}x"
        )
        return {'FINISHED'}


class AUXLINK_OT_auto_lattice(bpy.types.Operator):
    """Backward compatibility alias"""
    bl_idname = "auxlink.auto_lattice"
    bl_label = "Autolattice"
    bl_description = "Alias of auxlink.autolattice"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _resolve_target_mesh(context) is not None

    def execute(self, context):
        return bpy.ops.auxlink.autolattice()


class AUXLINK_OT_adjust_lattice(bpy.types.Operator):
    bl_idname = "auxlink.adjust_lattice"
    bl_label = "Adjust Lattice Grid"
    bl_description = "Subdivide the lattice interior; the outer cage stays locked"
    bl_options = {'REGISTER', 'UNDO'}

    points_u: IntProperty(name="Columns (U / X)", default=2, min=1, max=64)
    points_v: IntProperty(name="Rows (V / Y)", default=2, min=1, max=64)
    points_w: IntProperty(name="Height (W / Z)", default=2, min=1, max=64)

    @classmethod
    def poll(cls, context):
        return _find_lattice_pair(context)[2] is not None

    def invoke(self, context, event):
        lat_obj = _find_lattice_pair(context)[2]
        if lat_obj and lat_obj.data:
            self.points_u = lat_obj.data.points_u
            self.points_v = lat_obj.data.points_v
            self.points_w = lat_obj.data.points_w
        return context.window_manager.invoke_props_dialog(self, width=280)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.prop(self, "points_u")
        col.prop(self, "points_v")
        col.prop(self, "points_w")

    def execute(self, context):
        lat_obj = _find_lattice_pair(context)[2]
        if not lat_obj or not lat_obj.data:
            self.report({'ERROR'}, "No active lattice found")
            return {'CANCELLED'}

        was_edit = (lat_obj.mode == 'EDIT')
        if was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')

        _set_lattice_resolution(lat_obj, self.points_u, self.points_v, self.points_w)

        if was_edit:
            bpy.ops.object.mode_set(mode='EDIT')

        self.report({'INFO'}, f"Lattice resolution: {self.points_u}x{self.points_v}x{self.points_w}")
        return {'FINISHED'}


class AUXLINK_OT_refit_lattice(bpy.types.Operator):
    bl_idname = "auxlink.refit_lattice"
    bl_label = "Refit Autolattice to Mesh"
    bl_description = "Recompute the mesh bounds and refit the cage (resolution is kept)"
    bl_options = {'REGISTER', 'UNDO'}

    scale_factor: FloatProperty(
        name="Size Ratio", default=AUTOLATTICE_FACTOR, min=0.5, max=5.0, precision=2
    )

    @classmethod
    def poll(cls, context):
        mesh_obj, _mod, lat_obj = _find_lattice_pair(context)
        return mesh_obj is not None and lat_obj is not None

    def execute(self, context):
        mesh_obj, _mod, lat_obj = _find_lattice_pair(context)
        if not mesh_obj or not lat_obj:
            self.report({'ERROR'}, "Lattice pair not found")
            return {'CANCELLED'}

        sub_min = sub_max = None
        if mesh_obj.mode == 'EDIT':
            sub_min, sub_max = _calc_subselection_bounds(mesh_obj)

        if sub_min is not None and sub_max is not None:
            center = (sub_min + sub_max) / 2.0
            size = sub_max - sub_min
        else:
            center, size = _get_bounds(mesh_obj, context, allow_subselection=False)

        padded = _padded_size(size, self.scale_factor)
        lat_obj["auxlink_base_size"] = list(size)
        lat_obj["auxlink_center"] = list(center)
        _apply_cage_transform(lat_obj, mesh_obj, center, padded)

        self.report({'INFO'}, f"Autolattice refitted to {self.scale_factor:.2f}x of mesh")
        return {'FINISHED'}


class AUXLINK_OT_edit_lattice_mode(bpy.types.Operator):
    bl_idname = "auxlink.edit_lattice_mode"
    bl_label = "Edit Lattice"
    bl_description = "Select the lattice and enter Edit Mode to deform control points"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        lat_obj = _find_lattice_pair(context)[2]
        if not lat_obj:
            self.report({'ERROR'}, "No lattice found")
            return {'CANCELLED'}
        for o in context.selected_objects:
            o.select_set(False)
        context.view_layer.objects.active = lat_obj
        lat_obj.select_set(True)
        try:
            bpy.ops.object.mode_set(mode='EDIT')
        except Exception:
            pass
        return {'FINISHED'}


class AUXLINK_OT_apply_lattice(bpy.types.Operator):
    bl_idname = "auxlink.apply_lattice"
    bl_label = "Apply Lattice"
    bl_description = "Apply the lattice modifier to the mesh and delete the lattice object"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        mesh_obj, mod, _lat = _find_lattice_pair(context)
        return mesh_obj is not None and mod is not None

    def execute(self, context):
        mesh_obj, mod, lat_obj = _find_lattice_pair(context)
        if not mesh_obj or not mod:
            self.report({'ERROR'}, "No active lattice modifier found")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        context.view_layer.objects.active = mesh_obj
        try:
            bpy.ops.object.modifier_apply(modifier=mod.name)
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to apply modifier: {exc}")
            return {'CANCELLED'}

        _remove_lattice_object(lat_obj)
        mesh_obj.select_set(True)
        self.report({'INFO'}, f"Applied lattice deformation to '{mesh_obj.name}'")
        return {'FINISHED'}


class AUXLINK_OT_remove_lattice(bpy.types.Operator):
    bl_idname = "auxlink.remove_lattice"
    bl_label = "Remove Lattice"
    bl_description = "Remove the lattice modifier and object without applying"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        mesh_obj, mod, _lat = _find_lattice_pair(context)
        return mesh_obj is not None and mod is not None

    def execute(self, context):
        mesh_obj, mod, lat_obj = _find_lattice_pair(context)
        if not mesh_obj or not mod:
            self.report({'ERROR'}, "No active lattice modifier found")
            return {'CANCELLED'}

        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        mesh_obj.modifiers.remove(mod)
        _remove_lattice_object(lat_obj)

        context.view_layer.objects.active = mesh_obj
        mesh_obj.select_set(True)
        self.report({'INFO'}, f"Removed lattice from '{mesh_obj.name}'")
        return {'FINISHED'}


# =============================================================================
#  Menus and 3D Viewport Panels
# =============================================================================

class AUXLINK_MT_add_preset(bpy.types.Menu):
    bl_idname = "AUXLINK_MT_add_preset"
    bl_label = "Add Modifier Preset"

    def draw(self, context):
        layout = self.layout
        if not store.presets:
            layout.label(text="No presets saved yet", icon='INFO')
            return
        for name in store.presets:
            op = layout.operator(AUXLINK_OT_add_preset.bl_idname, text=name, icon='MODIFIER_DATA')
            op.preset_name = name


class AUXLINK_MT_main(bpy.types.Menu):
    bl_idname = "AUXLINK_MT_main"
    bl_label = "Auxlink"

    def draw(self, context):
        layout = self.layout
        layout.operator(AUXLINK_OT_save_preset.bl_idname, text="Save Modifier Preset", icon='PRESET_NEW')
        layout.menu(AUXLINK_MT_add_preset.bl_idname, text="Add Modifier Preset", icon='PRESET')

        layout.separator()
        layout.operator(AUXLINK_OT_autolattice.bl_idname, text="Autolattice", icon='OUTLINER_DATA_LATTICE')

        mesh_obj, mod, lat_obj = _find_lattice_pair(context)
        if lat_obj:
            layout.operator(AUXLINK_OT_adjust_lattice.bl_idname, text="Adjust Grid (Cols & Rows)...", icon='GRID')
            layout.operator(AUXLINK_OT_refit_lattice.bl_idname, text="Refit Autolattice to Mesh", icon='FULLSCREEN_ENTER')
            row = layout.row(align=True)
            row.operator(AUXLINK_OT_apply_lattice.bl_idname, text="Apply Autolattice", icon='CHECKMARK')
            row.operator(AUXLINK_OT_remove_lattice.bl_idname, text="Remove Autolattice", icon='CANCEL')


def _draw_auxlink_entry(self, context):
    layout = self.layout
    layout.separator()
    layout.menu(AUXLINK_MT_main.bl_idname, icon='MODIFIER')


_APPEND_TO = (
    "VIEW3D_MT_object_context_menu",
    "VIEW3D_MT_object",
    "VIEW3D_MT_edit_mesh_context_menu",
    "VIEW3D_MT_add",
)


class AUXLINK_PT_lattice_panel(bpy.types.Panel):
    bl_label = "Autolattice"
    bl_idname = "AUXLINK_PT_lattice_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Auxlink'

    def draw(self, context):
        layout = self.layout
        mesh_obj, mod, lat_obj = _find_lattice_pair(context)

        if not mesh_obj and not lat_obj:
            box = layout.box()
            box.label(text="Select a Mesh object", icon='INFO')
            return

        if lat_obj and lat_obj.data:
            lat_data = lat_obj.data
            box = layout.box()
            box.label(text=f"Lattice: {lat_obj.name}", icon='OUTLINER_DATA_LATTICE')

            col = box.column(align=True)
            col.label(text="Grid Resolution (Live):", icon='GRID')
            row = col.row(align=True)
            row.prop(lat_data, "points_u", text="Columns (U)")
            row.prop(lat_data, "points_v", text="Rows (V)")
            col.prop(lat_data, "points_w", text="Height (W)")
            col.prop(lat_data, "interpolation_type_u", text="Curve")
            col.prop(lat_obj, "scale", text="Cage Scale")

            row_tools = box.row(align=True)
            row_tools.operator(AUXLINK_OT_refit_lattice.bl_idname, text="Refit (1.3x)", icon='FULLSCREEN_ENTER')
            row_tools.operator(AUXLINK_OT_autolattice.bl_idname, text="Recreate", icon='FILE_REFRESH')
            row_tools.operator(AUXLINK_OT_adjust_lattice.bl_idname, text="Dialog...", icon='GRID')

            box.separator()
            row_mode = box.row(align=True)
            is_in_edit = (context.active_object == lat_obj and context.mode in {'EDIT', 'EDIT_LATTICE'})
            if is_in_edit:
                row_mode.operator("object.mode_set", text="Finish (Object Mode)", icon='CHECKMARK').mode = 'OBJECT'
            else:
                row_mode.operator(AUXLINK_OT_edit_lattice_mode.bl_idname, text="Edit Lattice Points", icon='EDITMODE_HLT')

            row_act = box.row(align=True)
            row_act.operator(AUXLINK_OT_apply_lattice.bl_idname, text="Apply", icon='CHECKMARK')
            row_act.operator(AUXLINK_OT_remove_lattice.bl_idname, text="Remove", icon='CANCEL')
        else:
            box = layout.box()
            box.label(text=f"Target: {mesh_obj.name}", icon='MESH_DATA')
            box.operator(AUXLINK_OT_autolattice.bl_idname, text="Autolattice", icon='OUTLINER_DATA_LATTICE')


# =============================================================================
#  Preferences
# =============================================================================

class AUXLINK_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__ or __name__

    active_preset: StringProperty(
        name="Active Preset",
        description="Preset currently open for detailed editing in Preferences",
        default="",
    )

    def draw(self, context):
        layout = self.layout

        row = layout.row(align=True)
        row.label(text="Presets (%d)" % len(store.presets), icon='PRESET')
        row.operator(AUXLINK_OT_import_presets.bl_idname, text="Import YAML", icon='IMPORT')
        row.operator(AUXLINK_OT_export_presets.bl_idname, text="Export YAML", icon='EXPORT')
        row.operator(AUXLINK_OT_restore_defaults.bl_idname, text="Restore Defaults", icon='RECOVER_LAST')
        row.operator(AUXLINK_OT_reload_presets.bl_idname, text="Reload", icon='FILE_REFRESH')

        box = layout.box()
        if not store.presets:
            box.label(text="No presets saved yet. Right-click a mesh > Auxlink > Save Modifier Preset", icon='INFO')
        else:
            for name, data in store.presets.items():
                is_active = (self.active_preset == name)
                p_box = box.box() if is_active else box

                row = p_box.row(align=True)
                edit_icon = 'DOWNARROW_HLT' if is_active else 'RIGHTARROW'
                sel_op = row.operator(AUXLINK_OT_select_preset_for_edit.bl_idname, text="", icon=edit_icon, emboss=False)
                sel_op.preset_name = name

                row.label(text=name, icon='MODIFIER_DATA')

                mods = data.get("modifiers", [])
                summary = " → ".join(m["name"] for m in mods) if mods else "(empty)"
                info = row.row(align=True)
                info.alignment = 'RIGHT'
                info.enabled = False
                info.label(text=summary)

                ren_op = row.operator(AUXLINK_OT_rename_preset.bl_idname, text="", icon='GREASEPENCIL')
                ren_op.old_name = name

                dup_op = row.operator(AUXLINK_OT_duplicate_preset.bl_idname, text="", icon='DUPLICATE')
                dup_op.preset_name = name

                del_op = row.operator(AUXLINK_OT_delete_preset.bl_idname, text="", icon='TRASH')
                del_op.preset_name = name

                if is_active:
                    col = p_box.column(align=False)
                    col.separator(factor=0.5)

                    bar = col.row(align=True)
                    bar.label(text=f"Editing Modifier Stack: {name}", icon='PREFERENCES')

                    apply_op = bar.operator(AUXLINK_OT_add_preset.bl_idname, text="Apply to Selected", icon='CHECKMARK')
                    apply_op.preset_name = name

                    upd_op = bar.operator(AUXLINK_OT_update_preset_from_active.bl_idname, text="Update from Active Object", icon='FILE_REFRESH')
                    upd_op.preset_name = name

                    mod_box = col.box()
                    if not mods:
                        mod_box.label(text="This preset has no modifiers.", icon='INFO')
                    else:
                        for idx, mod in enumerate(mods):
                            m_row = mod_box.row(align=True)
                            m_row.label(text=f"{idx + 1}.  {mod['name']}  [{mod['type']}]", icon='MODIFIER')

                            up_op = m_row.operator(AUXLINK_OT_move_preset_modifier.bl_idname, text="", icon='TRIA_UP')
                            up_op.preset_name = name
                            up_op.mod_index = idx
                            up_op.direction = 'UP'

                            dn_op = m_row.operator(AUXLINK_OT_move_preset_modifier.bl_idname, text="", icon='TRIA_DOWN')
                            dn_op.preset_name = name
                            dn_op.mod_index = idx
                            dn_op.direction = 'DOWN'

                            mren_op = m_row.operator(AUXLINK_OT_rename_preset_modifier.bl_idname, text="", icon='GREASEPENCIL')
                            mren_op.preset_name = name
                            mren_op.mod_index = idx

                            rm_op = m_row.operator(AUXLINK_OT_remove_preset_modifier.bl_idname, text="", icon='X')
                            rm_op.preset_name = name
                            rm_op.mod_index = idx

        layout.separator()
        row = layout.row(align=True)
        row.label(text=store.path, icon='FILE_TEXT')
        row.operator(AUXLINK_OT_open_presets_file.bl_idname, text="Edit in Text Editor", icon='TEXT')
        row.operator("wm.path_open", text="Open Folder", icon='FILE_FOLDER').filepath = store.directory


# =============================================================================
#  Registration
# =============================================================================

classes = (
    AUXLINK_OT_save_preset,
    AUXLINK_OT_add_preset,
    AUXLINK_OT_delete_preset,
    AUXLINK_OT_rename_preset,
    AUXLINK_OT_duplicate_preset,
    AUXLINK_OT_select_preset_for_edit,
    AUXLINK_OT_move_preset_modifier,
    AUXLINK_OT_remove_preset_modifier,
    AUXLINK_OT_rename_preset_modifier,
    AUXLINK_OT_update_preset_from_active,
    AUXLINK_OT_restore_defaults,
    AUXLINK_OT_open_presets_file,
    AUXLINK_OT_reload_presets,
    AUXLINK_OT_export_presets,
    AUXLINK_OT_import_presets,
    AUXLINK_OT_autolattice,
    AUXLINK_OT_auto_lattice,
    AUXLINK_OT_adjust_lattice,
    AUXLINK_OT_refit_lattice,
    AUXLINK_OT_edit_lattice_mode,
    AUXLINK_OT_apply_lattice,
    AUXLINK_OT_remove_lattice,
    AUXLINK_MT_add_preset,
    AUXLINK_MT_main,
    AUXLINK_PT_lattice_panel,
    AUXLINK_Preferences,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    store.load()
    for name in _APPEND_TO:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            menu.append(_draw_auxlink_entry)


def unregister():
    for name in _APPEND_TO:
        menu = getattr(bpy.types, name, None)
        if menu is not None:
            try:
                menu.remove(_draw_auxlink_entry)
            except Exception:
                pass
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass


if __name__ == "__main__":
    register()
