"""
ISO 15765-2 (ISO-TP) transporto sluoksnio biblioteka.

Bendra biblioteka visiems projekto skriptams. Anksciau kiekvienas scriptas
turejo savo ISO-TP parsavimo logika (kai kurios buvo neteisingos), todel
multi-frame zinutes nebuvo apdorojamos. Si biblioteka pakeicia visus tuos
duplikatus vienu sumtomu sprendimu.

ISO 15765-2 PCI (Protocol Control Information) baitas:
  Bitai 7-4: kadro tipas
    0x0X = Single Frame      — visa zinute viename CAN kadre
    0x1X = First Frame       — pirmas multi-frame zinutes kadras
    0x2X = Consecutive Frame — tasinys multi-frame
    0x3X = Flow Control      — gavejo back-pressure handshake

Trys vieso API:
  IsoTpReassembler   — busena turintis multi-frame surinkimas (rekomenduojama)
  extract_uds_sid    — be busenos, tik isgauna SID (analizatoriui)
  parse_iso_tp       — be busenos, senas formatas (diag_interpreter palaikymui)

Konstantos:
  PCI_SINGLE_FRAME, PCI_FIRST_FRAME, PCI_CONSECUTIVE_FRAME, PCI_FLOW_CONTROL
  PCI_TYPE_NAMES — zodynas su zmoniskais pavadinimais
"""

PCI_SINGLE_FRAME = 0
PCI_FIRST_FRAME = 1
PCI_CONSECUTIVE_FRAME = 2
PCI_FLOW_CONTROL = 3

PCI_TYPE_NAMES = {
    PCI_SINGLE_FRAME:      "Single Frame (SF)",
    PCI_FIRST_FRAME:       "First Frame (FF)",
    PCI_CONSECUTIVE_FRAME: "Consecutive Frame (CF)",
    PCI_FLOW_CONTROL:      "Flow Control (FC)",
}


class IsoTpReassembler:
    """
    Pilnas ISO 15765-2 multi-frame surinkimas.

    Saugo busena per CAN ID. Single Frame, First Frame + Consecutive Frame
    seka surenkama i viena pilna UDS pranesima. Flow Control kadrai ignoruojami
    (jie yra protokolu sluoksnio handshake, ne UDS duomenys).

    Naudojimas:
        r = IsoTpReassembler()
        for frame in frames:
            kind, payload = r.feed(frame.can_id, frame.data)
            if kind in ("single", "complete"):
                # `payload` yra pilnas UDS pranesimas (bytes)
                process_uds_message(payload)
    """

    def __init__(self):
        # can_id -> {"expected": int, "data": bytearray, "next_seq": int}
        self.buffers = {}

    def feed(self, can_id, data_bytes):
        """
        Pamaitinti reassembleri vienu CAN kadru.

        Grazina (kind, payload):
          ("single",   bytes) — pilnas UDS pranesimas viename SF kadre
          ("complete", bytes) — pilnas UDS pranesimas po multi-frame surinkimo
          ("partial",  None)  — multi-frame busena (FF arba CF), dar ne pilna
          ("ignored",  None)  — Flow Control arba kazkas ko nezinome
          ("error",    None)  — sequence error / invalid frame, busena isvalyta
        """
        if not data_bytes:
            return ("error", None)

        pci = data_bytes[0]
        pci_type = (pci >> 4) & 0x0F

        # --- Single Frame ---
        if pci_type == PCI_SINGLE_FRAME:
            length = pci & 0x0F
            if length == 0 or length > len(data_bytes) - 1:
                return ("error", None)
            return ("single", bytes(data_bytes[1:1 + length]))

        # --- First Frame ---
        if pci_type == PCI_FIRST_FRAME:
            if len(data_bytes) < 8:
                return ("error", None)
            total_len = ((pci & 0x0F) << 8) | data_bytes[1]
            if total_len <= 6:
                # Klaidingai suformatuotas FF (turetu buti SF) — vis tiek priimam
                return ("single", bytes(data_bytes[2:2 + total_len]))
            # Pradzia: 6 baitai is FF (po 2 PCI baitu)
            self.buffers[can_id] = {
                "expected": total_len,
                "data": bytearray(data_bytes[2:8]),
                "next_seq": 1,   # CF sekvencija pradeda nuo 1 (FF yra implicitiskai 0)
            }
            return ("partial", None)

        # --- Consecutive Frame ---
        if pci_type == PCI_CONSECUTIVE_FRAME:
            seq = pci & 0x0F
            buf = self.buffers.get(can_id)
            if buf is None:
                # CF be FF — apsileidimas, ignoruojam
                return ("ignored", None)
            if seq != buf["next_seq"]:
                # Sequence error — atmetam buseno
                del self.buffers[can_id]
                return ("error", None)
            remaining = buf["expected"] - len(buf["data"])
            chunk = bytes(data_bytes[1:1 + min(7, remaining)])
            buf["data"].extend(chunk)
            buf["next_seq"] = (buf["next_seq"] + 1) & 0x0F
            if len(buf["data"]) >= buf["expected"]:
                payload = bytes(buf["data"][:buf["expected"]])
                del self.buffers[can_id]
                return ("complete", payload)
            return ("partial", None)

        # --- Flow Control ---
        if pci_type == PCI_FLOW_CONTROL:
            return ("ignored", None)

        return ("error", None)

    def reset(self, can_id=None):
        """Isvalyti busena. Be argumento — visa, su can_id — tik vieno kadro."""
        if can_id is None:
            self.buffers.clear()
        else:
            self.buffers.pop(can_id, None)


def extract_uds_sid(data_bytes):
    """
    Be busenos. Isgauti UDS Service ID is vieno ISO-TP enkapsuliuoto kadro.

    SID egzistuoja tik Single Frame ir First Frame kadruose.
    Consecutive Frame ir Flow Control jokio SID nesa.

    Grazina (sid, pci_type):
      sid       — UDS Service ID baitas, arba None jei kadras nera SF/FF
      pci_type  — kadro tipas (PCI_SINGLE_FRAME, PCI_FIRST_FRAME, ...)
                  arba None jei tuscia data
    """
    if not data_bytes:
        return None, None

    pci = data_bytes[0]
    pci_type = (pci >> 4) & 0x0F

    if pci_type == PCI_SINGLE_FRAME:
        length = pci & 0x0F
        if length >= 1 and len(data_bytes) >= 2:
            return data_bytes[1], pci_type
        return None, pci_type

    if pci_type == PCI_FIRST_FRAME:
        if len(data_bytes) >= 3:
            return data_bytes[2], pci_type
        return None, pci_type

    return None, pci_type


def parse_iso_tp(data_bytes):
    """
    Be busenos, senas formatas (diag_interpreter palaikymui).

    Grazina (frame_type_str, payload_or_none):
      frame_type_str — "SF", "FF", "CF<n>" (n yra sequence), "FC", arba None
      payload_or_none — duomenys po PCI baitu (be tikrosios reassembly)

    Pastaba: si funkcija nedaro multi-frame surinkimo. FF gauni tik pirma 6
    baitus, CF — tik to vieno kadro turini. Tikram surinkimui naudok
    IsoTpReassembler vietoj sito.
    """
    if len(data_bytes) < 1:
        return None, None

    pci_type = (data_bytes[0] >> 4) & 0x0F

    if pci_type == PCI_SINGLE_FRAME:
        length = data_bytes[0] & 0x0F
        return "SF", data_bytes[1:1 + length]

    if pci_type == PCI_FIRST_FRAME and len(data_bytes) >= 2:
        # length = ((data_bytes[0] & 0x0F) << 8) | data_bytes[1]   # 12-bit total
        return "FF", data_bytes[2:]

    if pci_type == PCI_CONSECUTIVE_FRAME:
        seq = data_bytes[0] & 0x0F
        return f"CF{seq}", data_bytes[1:]

    if pci_type == PCI_FLOW_CONTROL:
        return "FC", data_bytes[1:]

    return None, data_bytes
