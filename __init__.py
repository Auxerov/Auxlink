bl_info = {
    "name": "Auxlink",
    "author": "Auxerov",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "location": "3D Viewport > Right-Click > Auxlink  (also: Object menu / F3 search)",
    "description": "Save modifier stacks as presets, add them back with one click, import/export them as YAML",
    "category": "Object",
}

import json
import math
import os
import re
import shutil

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ExportHelper, ImportHelper


# =============================================================================
#  Minimal YAML (subset) reader / writer  -- no external dependencies
#  Supports: block mappings, block sequences, flow lists/maps (single line),
#  quoted/plain scalars, comments.  Enough for Auxlink's own format and for
#  hand-edited files that stay within the same style.
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
        return _SKIP  # nested structs (curve mappings, profiles...) are not supported
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
    return _SKIP  # nested groups etc.


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

    # Only some modifiers (Geometry Nodes) support custom IDProperties; others raise TypeError.
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
    # node_group must be assigned first so the node inputs exist afterwards
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

    def load(self):
        self.presets = {}
        path = self.path
        if not os.path.isfile(path):
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
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(dump_yaml(presets_to_document(self.presets), YAML_HEADER))
        os.replace(tmp, path)


store = _Store()


def _redraw_all():
    wm = bpy.context.window_manager
    for window in wm.windows:
        for area in window.screen.areas:
            area.tag_redraw()


# =============================================================================
#  Operators
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
            self.report({'INFO'}, "Deleted preset '%s'" % self.preset_name)
        _redraw_all()
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
#  Menus
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


def _draw_auxlink_entry(self, context):
    layout = self.layout
    layout.separator()
    layout.menu(AUXLINK_MT_main.bl_idname, icon='MODIFIER')


_APPEND_TO = ("VIEW3D_MT_object_context_menu", "VIEW3D_MT_object")


# =============================================================================
#  Preferences
# =============================================================================

class AUXLINK_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__ or __name__

    def draw(self, context):
        layout = self.layout

        box = layout.box()
        box.label(text="Saved Presets (%d)" % len(store.presets), icon='PRESET')
        if not store.presets:
            box.label(text="Nothing here yet: right-click a model > Auxlink > Save Modifier Preset", icon='INFO')
        for name, data in store.presets.items():
            row = box.row(align=True)
            row.label(text=name, icon='MODIFIER_DATA')
            info = row.row(align=True)
            info.alignment = 'RIGHT'
            info.enabled = False
            info.label(text=", ".join(m["name"] for m in data["modifiers"]) or "(empty)")
            op = row.operator(AUXLINK_OT_delete_preset.bl_idname, text="", icon='TRASH')
            op.preset_name = name

        row = layout.row(align=True)
        row.operator(AUXLINK_OT_import_presets.bl_idname, text="Import YAML", icon='IMPORT')
        row.operator(AUXLINK_OT_export_presets.bl_idname, text="Export YAML", icon='EXPORT')
        row.operator(AUXLINK_OT_reload_presets.bl_idname, text="Reload", icon='FILE_REFRESH')

        row = layout.row(align=True)
        row.label(text=store.path, icon='FILE_TEXT')
        row.operator("wm.path_open", text="Open Folder", icon='FILE_FOLDER').filepath = store.directory


# =============================================================================
#  Registration
# =============================================================================

classes = (
    AUXLINK_OT_save_preset,
    AUXLINK_OT_add_preset,
    AUXLINK_OT_delete_preset,
    AUXLINK_OT_reload_presets,
    AUXLINK_OT_export_presets,
    AUXLINK_OT_import_presets,
    AUXLINK_MT_add_preset,
    AUXLINK_MT_main,
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
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
