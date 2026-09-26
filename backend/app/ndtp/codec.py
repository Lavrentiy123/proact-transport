"""Кодек NDTP: разбор и сборка кадров ``[NPL 15 B][NPH 10 B][тело]``.

Спецификация — ``data/dataset_docs/Emulator-and-Telematic-Packets-Specification.md`` §5–6.
Все поля little-endian, структуры packed. Проверено на живом образе ``ndtp-telemetry-emulator:1.0``:

- CRC-16/Modbus (poly ``0xA001``, init ``0xFFFF``) считается по NPH + телу; в поле ``crc`` заголовка
  NPL он лежит **с переставленными байтами**: прочитанное как u16 LE значение = ``swap16(crc)``;
- handshake: NPH ``(serviceId=0, type=100)``, тело 18 байт;
- realtime: NPH ``(1, 101)``, тело — ячейки ``[type u8][number u8][payload]``, ``G6CellNav00`` первая.

Для потока используйте :class:`FrameDecoder` (буфер между чтениями сокета) или :func:`iter_frames`.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field

SIGNATURE = 0x7E7E
SIGNATURE_BYTES = b"\x7e\x7e"
NPL = struct.Struct("<HHHHBIH")          # signature, dataSize, flags, crc, type, peerAddress, requestId — 15 B
NPH = struct.Struct("<HHHI")             # serviceId, type, flags, requestId — 10 B
HANDSHAKE = struct.Struct("<HHHIII")     # protoVersionHigh, protoVersionLow, flags, peerAddress, maxPacketSize, reserved
NAV = struct.Struct("<IIIBBHHHHHBB")     # G6CellNav00 — 26 B
NPL_TYPE_NPH = 0x02
SVC_GENERIC_CONTROLS, TYPE_CONN_REQUEST = 0, 100
SVC_NAVDATA, TYPE_REALTIME = 1, 101
NPH_FLAG_REQUEST = 0x0001
CELL_NAV00 = 0
# Длины payload известных ячеек (без 2 байт type/number). Незнакомый type — дальше разбирать нельзя.
CELL_SIZE = {0: 26, 2: 26, 8: 6, 10: 37, 15: 50, 16: 8}
MAX_DATA_SIZE = 65535
U16_MAX, U32_MAX = 0xFFFF, 0xFFFFFFFF


def _crc_table() -> list[int]:
    table = []
    for b in range(256):
        c = b
        for _ in range(8):
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
        table.append(c)
    return table


_CRC_TABLE = _crc_table()


def crc16_modbus(data: bytes) -> int:
    """CRC-16/Modbus (poly 0xA001 reflected, init 0xFFFF)."""
    crc = 0xFFFF
    tbl = _CRC_TABLE
    for b in data:
        crc = (crc >> 8) ^ tbl[(crc ^ b) & 0xFF]
    return crc


def swap16(x: int) -> int:
    """Переставляет байты u16."""
    return ((x & 0xFF) << 8) | (x >> 8)


@dataclass(slots=True)
class NavFix:
    """Навигационная ячейка ``G6CellNav00`` в физических единицах.

    Attributes:
        ts: Unix-время, секунды (как в пакете).
        lat, lon: градусы со знаком (знак — из битов 5/6 ``extraDop``).
        valid: достоверность координат (бит 7).
        speed: средняя скорость ``speedAvg``, км/ч.
        speed_max: ``speedMax``, км/ч.
        course: курс, градусы.
        alt: высота, м.
        nsat, pdop, bat, track: служебные поля ячейки.
        bits: байт ``extraDop`` целиком.
    """

    ts: int
    lat: float
    lon: float
    valid: bool
    speed: int
    speed_max: int = 0
    course: int = 0
    alt: int = 0
    nsat: int = 0
    pdop: int = 0
    bat: int = 0
    track: int = 0
    bits: int = 0


@dataclass(slots=True)
class Frame:
    """Разобранный кадр NDTP.

    Attributes:
        unit_id: ``peerAddress`` из NPL (id бортового терминала).
        service, ptype: ``serviceId`` и ``type`` из NPH.
        request_id: ``requestId`` из NPH.
        handshake: поля тела handshake или ``None``.
        navs: навигационные ячейки realtime-пакета.
        cells: типы всех ячеек по порядку (для отладки).
        unknown_cell: встретилась ячейка незнакомого типа (разбор тела остановлен на ней).
    """

    unit_id: int
    service: int
    ptype: int
    request_id: int
    handshake: dict | None = None
    navs: list[NavFix] = field(default_factory=list)
    cells: list[int] = field(default_factory=list)
    unknown_cell: bool = False

    @property
    def is_handshake(self) -> bool:
        return (self.service, self.ptype) == (SVC_GENERIC_CONTROLS, TYPE_CONN_REQUEST)

    @property
    def is_realtime(self) -> bool:
        return (self.service, self.ptype) == (SVC_NAVDATA, TYPE_REALTIME)


@dataclass
class DecodeStats:
    """Счётчики потокового разбора (для ``/metrics``)."""

    frames: int = 0
    crc_errors: int = 0
    garbage_bytes: int = 0
    bad_headers: int = 0
    unknown_cells: int = 0


def parse_nav(payload: bytes, offset: int = 0) -> NavFix:
    """Разбирает 26 байт ``G6CellNav00``."""
    ts, lon, lat, bits, bat, v_avg, v_max, course, track, alt, nsat, pdop = NAV.unpack_from(payload, offset)
    return NavFix(ts=ts, lat=lat / 1e7 * (1.0 if bits & 0x20 else -1.0), lon=lon / 1e7 * (1.0 if bits & 0x40 else -1.0),
                  valid=bool(bits & 0x80), speed=v_avg, speed_max=v_max, course=course, alt=alt, nsat=nsat,
                  pdop=pdop, bat=bat, track=track, bits=bits)


def parse_body(unit_id: int, body: bytes) -> Frame:
    """Разбирает NPH + тело (CRC уже проверен)."""
    service, ptype, _flags, rid = NPH.unpack_from(body, 0)
    fr = Frame(unit_id=unit_id, service=service, ptype=ptype, request_id=rid)
    if fr.is_handshake and len(body) >= NPH.size + HANDSHAKE.size:
        hi, lo, fl, peer, maxp, _res = HANDSHAKE.unpack_from(body, NPH.size)
        fr.handshake = {"proto_high": hi, "proto_low": lo, "flags": fl, "peer_address": peer, "max_packet_size": maxp}
    elif fr.is_realtime:
        off = NPH.size
        while off + 2 <= len(body):
            ctype = body[off]
            off += 2
            fr.cells.append(ctype)
            size = CELL_SIZE.get(ctype)
            if size is None or off + size > len(body):
                fr.unknown_cell = True
                break
            if ctype == CELL_NAV00:
                fr.navs.append(parse_nav(body, off))
            off += size
    return fr


def parse_frame(frame: bytes) -> Frame:
    """Разбирает один целый кадр (NPL + NPH + тело).

    Raises:
        ValueError: неверная сигнатура, длина или CRC.
    """
    if len(frame) < NPL.size + NPH.size:
        raise ValueError("frame too short")
    sig, size, _fl, crc_field, _typ, unit_id, _rid = NPL.unpack_from(frame, 0)
    if sig != SIGNATURE:
        raise ValueError("bad signature")
    body = frame[NPL.size:NPL.size + size]
    if size < NPH.size or len(body) != size:
        raise ValueError("bad dataSize")
    if crc_field != swap16(crc16_modbus(body)):
        raise ValueError("bad crc")
    return parse_body(unit_id, body)


def iter_frames(buf: bytes | bytearray, stats: DecodeStats | None = None) -> tuple[list[Frame], bytes]:
    """Выделяет из буфера все целые кадры.

    Мусор до сигнатуры пропускается (ресинхронизация по ``0x7E 0x7E``); кадр с неверным CRC
    отбрасывается и учитывается в ``stats.crc_errors``, исключение не бросается.

    Args:
        buf: накопленные байты сокета.
        stats: счётчики (по желанию).

    Returns:
        ``(frames, rest)`` — разобранные кадры и хвост, который надо дополнить следующим чтением.
    """
    st = stats if stats is not None else DecodeStats()
    frames: list[Frame] = []
    mv = bytes(buf)
    pos, n = 0, len(mv)
    while True:
        j = mv.find(SIGNATURE_BYTES, pos)
        if j < 0:
            # оставляем последний байт: он может оказаться первой половиной сигнатуры
            keep = 1 if n > pos and mv[-1] == 0x7E else 0
            st.garbage_bytes += (n - pos) - keep
            return frames, mv[n - keep:] if keep else b""
        if j > pos:
            st.garbage_bytes += j - pos
            pos = j
        if n - pos < NPL.size:
            return frames, mv[pos:]
        sig, size, _fl, crc_field, typ, unit_id, _rid = NPL.unpack_from(mv, pos)
        if size < NPH.size or size > MAX_DATA_SIZE or typ != NPL_TYPE_NPH:
            st.bad_headers += 1
            pos += 1          # ложная сигнатура — ищем следующую
            continue
        end = pos + NPL.size + size
        if end > n:
            return frames, mv[pos:]
        body = mv[pos + NPL.size:end]
        if crc_field != swap16(crc16_modbus(body)):
            st.crc_errors += 1
            pos = end
            continue
        fr = parse_body(unit_id, body)
        st.frames += 1
        if fr.unknown_cell:
            st.unknown_cells += 1
        frames.append(fr)
        pos = end


class FrameDecoder:
    """Потоковый декодер одного TCP-соединения: копит байты между чтениями."""

    def __init__(self, stats: DecodeStats | None = None):
        self.stats = stats if stats is not None else DecodeStats()
        self._buf = b""

    def feed(self, data: bytes) -> list[Frame]:
        """Добавляет прочитанные байты и возвращает целые кадры."""
        frames, self._buf = iter_frames(self._buf + data, self.stats)
        return frames

    @property
    def pending(self) -> int:
        """Сколько байт ждут продолжения кадра."""
        return len(self._buf)


# ---------------- энкодер ----------------
def encode_frame(unit_id: int, service: int, ptype: int, request_id: int, body: bytes) -> bytes:
    """Собирает кадр: NPL (CRC байт-свапнут, как у эмулятора) + NPH (флаг request) + тело."""
    payload = NPH.pack(service, ptype, NPH_FLAG_REQUEST, request_id & U32_MAX) + body
    crc = crc16_modbus(payload)
    npl = NPL.pack(SIGNATURE, len(payload), 0, swap16(crc), NPL_TYPE_NPH, unit_id & U32_MAX, 0)
    return npl + payload


def encode_handshake(unit_id: int, rid: int = 1) -> bytes:
    """Кадр ``NPH_SGC_CONN_REQUEST`` (версия протокола 6.2, maxPacketSize 65535)."""
    return encode_frame(unit_id, SVC_GENERIC_CONTROLS, TYPE_CONN_REQUEST, rid,
                        HANDSHAKE.pack(6, 2, 0, unit_id & U32_MAX, 65535, 0))


def _u16(x, lo: int = 0) -> int:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return lo
    return int(min(max(round(float(x)), lo), U16_MAX))


def encode_nav(unit_id: int, rid: int, ts: int, lat: float, lon: float, speed: float = 0.0, course: float = 0.0,
               valid: bool = True, alt: float = 0.0) -> bytes:
    """Кадр ``NPH_SND_REALTIME`` с одной ячейкой ``G6CellNav00``.

    Координаты NaN (невалидный фикс датасета) кодируются нулями с ``valid=False``.
    Скорость, курс и высота обрезаются в диапазон u16, NaN → 0.
    """
    ok = lat is not None and lon is not None and math.isfinite(lat) and math.isfinite(lon)
    lat_v, lon_v = (float(lat), float(lon)) if ok else (0.0, 0.0)
    bits = (0x20 if lat_v >= 0 else 0) | (0x40 if lon_v >= 0 else 0) | (0x80 if (valid and ok) else 0)
    spd = _u16(speed)
    cell = bytes((CELL_NAV00, 0)) + NAV.pack(
        int(ts) & U32_MAX, int(round(abs(lon_v) * 1e7)), int(round(abs(lat_v) * 1e7)), bits, 0,
        spd, spd, _u16(course) % 361, 0, _u16(alt), 0, 0)
    return encode_frame(unit_id, SVC_NAVDATA, TYPE_REALTIME, rid, cell)
