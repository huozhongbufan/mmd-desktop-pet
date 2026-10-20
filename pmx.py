"""PMX 2.0 parser — pure standard library, zero dependencies.

Handles both spec-compliant files **and** a real-world non-standard exporter
whose quirks are documented inline (and in docs/PITFALLS.md):

  1. Header is 17 bytes (not 20) — reading settings at offset 20 lands in the
     model-name field, giving garbage index sizes.
  2. Every vertex weight block is followed by a 4-byte pad float. Verified by
     solving the vertex-section length from the texture-section offset.
  3. Bone `flags` is 1 byte (spec says 2) and the bone tail layout differs, so
     bones are walked by anchoring on the JP-name strings instead of sizes.

Bone / morph parsing is best-effort: on the non-standard layout the parse
raises, the caller keeps `bones == []`, and identity-skinning rendering still
works (vertices are stored in bind pose).

Format reference: PMX 2.0 / 2.1 public specification.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field


@dataclass
class Material:
    name_jp: str = ""
    name_en: str = ""
    diffuse: tuple = (1.0, 1.0, 1.0, 1.0)
    specular: tuple = (0.0, 0.0, 0.0)
    spec_strength: float = 0.0
    ambient: tuple = (0.0, 0.0, 0.0)
    flags: int = 0
    edge_color: tuple = (0.0, 0.0, 0.0, 1.0)
    edge_size: float = 1.0
    tex_idx: int = -1
    sphere_idx: int = -1
    sphere_mode: int = 0
    toon: int = 0            # 0 = shared toon index, 1 = texture index
    toon_value: int = 0
    memo: str = ""
    face_count: int = 0


@dataclass
class Vertex:
    pos: tuple = (0.0, 0.0, 0.0)
    normal: tuple = (0.0, 0.0, 1.0)
    uv: tuple = (0.0, 0.0)
    weight_type: int = 0
    bones: tuple = ()
    weights: tuple = ()
    sdef_c: tuple = (0.0, 0.0, 0.0)
    sdef_r0: tuple = (0.0, 0.0, 0.0)
    sdef_r1: tuple = (0.0, 0.0, 0.0)


@dataclass
class Bone:
    name_jp: str = ""
    name_en: str = ""
    pos: tuple = (0.0, 0.0, 0.0)
    parent: int = -1
    layer: int = 0
    flags: int = 0


@dataclass
class Pmx:
    name_jp: str = ""
    name_en: str = ""
    vertices: list = field(default_factory=list)
    indices: list = field(default_factory=list)
    textures: list = field(default_factory=list)
    materials: list = field(default_factory=list)
    bones: list = field(default_factory=list)
    morph_names: list = field(default_factory=list)
    morph_counts: dict = field(default_factory=dict)
    bone_parse_error: str = ""
    morph_parse_error: str = ""


class Parser:
    def __init__(self, data: bytes):
        self.data = data
        if data[:4] != b"PMX ":
            raise ValueError("not a PMX file")
        self.version = struct.unpack_from("<f", data, 4)[0]
        self.settings_count = data[8]
        (self.encoding, self.n_uv, self.vi_sz, self.ti_sz,
         self.mi_sz, self.bi_sz, self.mo_sz, self.rb_sz) = \
            struct.unpack_from("<8B", data, 9)
        # header = 4 (sig) + 4 (version) + 1 (count) + 8 (settings) = 17
        self.off = 17

    # ---- primitive readers -------------------------------------------------

    def u8(self) -> int:
        v = self.data[self.off]
        self.off += 1
        return v

    def u16(self) -> int:
        v = struct.unpack_from("<H", self.data, self.off)[0]
        self.off += 2
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.data, self.off)[0]
        self.off += 4
        return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.data, self.off)[0]
        self.off += 4
        return v

    def vec3(self) -> tuple:
        v = struct.unpack_from("<3f", self.data, self.off)
        self.off += 12
        return v

    def vec4(self) -> tuple:
        v = struct.unpack_from("<4f", self.data, self.off)
        self.off += 16
        return v

    def idx(self, size: int) -> int:
        if size == 1:
            return self.u8()
        if size == 2:
            return self.u16()
        return self.u32()

    def string(self) -> str:
        n = self.u32()
        raw = self.data[self.off:self.off + n]
        self.off += n
        if self.encoding == 0:
            return raw.decode("utf-16-le", "replace")
        return raw.decode("utf-8", "replace")

    # ---- sections ----------------------------------------------------------

    def parse(self) -> Pmx:
        pmx = Pmx()
        pmx.name_jp = self.string()
        pmx.name_en = self.string()
        self.string()          # comment JP
        self.string()          # comment EN
        self._parse_vertices(pmx)
        self._parse_indices(pmx)
        self._parse_textures(pmx)
        self._parse_materials(pmx)
        try:
            self._parse_bones(pmx)
        except Exception as exc:            # non-standard bone layout
            pmx.bones = []
            pmx.bone_parse_error = str(exc)[:160]
        try:
            self._parse_morphs(pmx)
        except Exception as exc:
            pmx.morph_names = []
            pmx.morph_counts = {}
            pmx.morph_parse_error = str(exc)[:160]
        return pmx

    def _parse_vertices(self, pmx: Pmx) -> None:
        n = self.u32()
        for _ in range(n):
            v = Vertex()
            v.pos = self.vec3()
            v.normal = self.vec3()
            v.uv = struct.unpack_from("<2f", self.data, self.off)
            self.off += 8
            for _k in range(self.n_uv):
                self.off += 16
            wt = self.u8()
            v.weight_type = wt
            if wt == 0:                                  # BDEF1
                v.bones = (self.idx(self.bi_sz),)
                v.weights = (1.0,)
            elif wt == 1:                                # BDEF2
                b1 = self.idx(self.bi_sz)
                b2 = self.idx(self.bi_sz)
                w1 = self.f32()
                v.bones = (b1, b2)
                v.weights = (w1, 1.0 - w1)
            elif wt == 2:                                # BDEF4
                v.bones = tuple(self.idx(self.bi_sz) for _ in range(4))
                v.weights = tuple(self.f32() for _ in range(4))
            elif wt == 3:                                # SDEF
                v.bones = tuple(self.idx(self.bi_sz) for _ in range(4))
                v.weights = tuple(self.f32() for _ in range(4))
                v.sdef_c = self.vec3()
                v.sdef_r0 = self.vec3()
                v.sdef_r1 = self.vec3()
            # NON-STANDARD: a 4-byte pad follows every weight block.
            self.off += 4
            pmx.vertices.append(v)

    def _parse_indices(self, pmx: Pmx) -> None:
        n = self.u32()
        pmx.indices = [self.idx(self.vi_sz) for _ in range(n)]

    def _parse_textures(self, pmx: Pmx) -> None:
        n = self.u32()
        pmx.textures = [self.string() for _ in range(n)]

    def _parse_materials(self, pmx: Pmx) -> None:
        n = self.u32()
        for _ in range(n):
            m = Material()
            m.name_jp = self.string()
            m.name_en = self.string()
            m.diffuse = self.vec4()
            m.specular = self.vec3()
            m.spec_strength = self.f32()
            m.ambient = self.vec3()
            m.flags = self.u8()
            m.edge_color = self.vec4()
            m.edge_size = self.f32()
            m.tex_idx = self.idx(self.ti_sz)
            m.sphere_idx = self.idx(self.ti_sz)
            m.sphere_mode = self.u8()
            m.toon = self.u8()
            m.toon_value = self.u8()
            m.memo = self.string()
            m.face_count = self.u32()
            pmx.materials.append(m)

    def _parse_bones(self, pmx: Pmx) -> None:
        """Walk bones by anchoring on JP name strings.

        The non-standard exporter writes 1-byte bone flags and an unknown tail
        layout, so the standard walk desyncs on the second bone. Instead: scan
        the bone region for valid length-prefixed UTF-16 strings, treat a
        string as a bone start when it lies >= 22 bytes past the previous one
        (EN names sit flush against their JP name, gap 0), and require the
        resulting count to equal the declared bone count.
        """
        n = self.u32()
        anchor = self.data.find("あ".encode("utf-16-le"), self.off)
        if anchor < 0:
            raise ValueError("morph anchor not found")
        limit = anchor - 8

        scan: list[tuple[int, int]] = []
        pos = self.off
        while pos < limit:
            if pos + 4 > limit:
                break
            ln = struct.unpack_from("<I", self.data, pos)[0]
            if 1 <= ln <= 128 and ln % 2 == 0 and pos + 4 + ln <= limit:
                try:
                    s = self.data[pos + 4:pos + 4 + ln].decode("utf-16-le")
                    ok = bool(s) and all(0x20 <= ord(c) < 0xA000 for c in s)
                except UnicodeDecodeError:
                    ok = False
                if ok:
                    scan.append((pos, ln))
                    pos += 4 + ln
                    continue
            pos += 1

        starts = [scan[0][0]] if scan else []
        for j in range(1, len(scan)):
            prev_off, prev_ln = scan[j - 1]
            gap = scan[j][0] - (prev_off + 4 + prev_ln)
            if gap >= 22:
                starts.append(scan[j][0])

        if len(starts) != n:
            raise ValueError(f"bone anchors {len(starts)} != declared {n}")

        for base in starts:
            ln = struct.unpack_from("<I", self.data, base)[0]
            b = Bone()
            b.name_jp = self.data[base + 4:base + 4 + ln].decode(
                "utf-16-le", "replace")
            o2 = base + 4 + ln
            ln2 = struct.unpack_from("<I", self.data, o2)[0]
            b.name_en = (self.data[o2 + 4:o2 + 4 + ln2].decode(
                "utf-16-le", "replace") if ln2 else "")
            o3 = o2 + 4 + ln2
            b.pos = struct.unpack_from("<3f", self.data, o3)
            b.parent = struct.unpack_from("<h", self.data, o3 + 12)[0]
            b.layer = struct.unpack_from("<I", self.data, o3 + 14)[0]
            b.flags = self.data[o3 + 18]
            pmx.bones.append(b)
        self.off = limit

    def _parse_morphs(self, pmx: Pmx) -> None:
        n = self.u32()
        for _ in range(n):
            name_jp = self.string()
            self.string()
            self.u8()                      # panel
            mtype = self.u8()
            count = self.u32()
            pmx.morph_names.append(name_jp)
            pmx.morph_counts[name_jp] = count
            if mtype == 0:                 # group
                for _c in range(count):
                    self.idx(self.mo_sz)
                    self.f32()
            elif mtype == 1:               # vertex
                for _c in range(count):
                    self.idx(self.vi_sz)
                    self.vec3()
            elif mtype in (3, 4, 5, 6, 7):
                for _c in range(count):
                    self.idx(2 if mtype == 3 else 4)
                    if mtype == 3:
                        self.vec3()
                        self.vec4()
                    elif mtype in (4, 5, 6):
                        self.vec4()
                    elif mtype == 7:
                        self.u8()
                        self.vec4()
                        self.vec3()
                        self.f32()
                        self.vec4()
                        self.vec4()
                        self.vec4()


def load(path: str) -> Pmx:
    """Parse a .pmx file from disk."""
    with open(path, "rb") as f:
        data = f.read()
    return Parser(data).parse()
