"""
UDS (ISO 14229) protokolu konstantos ir pagalbines funkcijos.

Bendra biblioteka visiems projekto skriptams. Anksciau kiekvienas interpretatorius
turejo savo kopija UDS_SERVICES, NRC_NAMES, SESSION_NAMES ir DTC_SUBFUNCTIONS
zodyno (4 kopijos kiekvieno!) — si biblioteka pakeicia juos vienu sumtomu sprendimu.

Ji vyriskai dengia ISO 14229-1 servisus, neigiamus atsakymu kodus ir DTC sub-funkcijas,
plius dazniausius OEM-specifinius pratesimus (BMW, Mercedes, KWP2000 paveldas).

Pagrindiniai vieso API:
  UDS_SERVICES        — SID -> servisas, pavadinimas
  NRC_NAMES           — NRC byte -> klaidos pavadinimas
  SESSION_NAMES       — sesijos byte -> sesijos pavadinimas
  DTC_SUBFUNCTIONS    — Service 0x19 sub-funkcijos

  decode_service(sid)              — pavadina ir teigiamus, ir uzklausu SID
  decode_nrc(byte)                 — NRC pavadinimas arba 0x.. fallback
  decode_session(byte)             — sesijos pavadinimas
  decode_dtc_subfunc(byte)         — DTC sub-funkcijos pavadinimas

Pridek nauja servisa cia ir VISI interpretatoriai jautis automatiskai.
"""

# ============================================================================
# UDS Service Identifiers (ISO 14229-1)
# ============================================================================

UDS_SERVICES = {
    # ISO 14229-1 standartiniai servisai
    0x10: "DiagnosticSessionControl",
    0x11: "ECUReset",
    0x14: "ClearDiagnosticInformation",
    0x19: "ReadDTCInformation",
    0x22: "ReadDataByIdentifier",
    0x23: "ReadMemoryByAddress",
    0x24: "ReadScalingDataByIdentifier",
    0x27: "SecurityAccess",
    0x28: "CommunicationControl",
    0x2A: "ReadDataByPeriodicIdentifier",
    0x2C: "DynamicallyDefineDataIdentifier",
    0x2E: "WriteDataByIdentifier",
    0x2F: "InputOutputControlByIdentifier",
    0x31: "RoutineControl",
    0x34: "RequestDownload",
    0x35: "RequestUpload",
    0x36: "TransferData",
    0x37: "RequestTransferExit",
    0x38: "RequestFileTransfer",
    0x3D: "WriteMemoryByAddress",
    0x3E: "TesterPresent",
    0x83: "AccessTimingParameter",
    0x84: "SecuredDataTransmission",
    0x85: "ControlDTCSetting",
    0x86: "ResponseOnEvent",
    0x87: "LinkControl",

    # KWP2000 (ISO 14230) paveldas — kai kurie ECU vis dar atsako i juos
    0x01: "StartCommunication (KWP)",
    0x02: "StopCommunication (KWP)",
    0x18: "ReadDTCByStatus (KWP)",
    0x20: "ReturnToNormalOperation (KWP)",
    0x82: "StopCommunication (KWP)",
}


# ============================================================================
# UDS Negative Response Codes (NRC, ISO 14229-1 Table A.1)
# ============================================================================

NRC_NAMES = {
    0x10: "generalReject",
    0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat",
    0x14: "responseTooLong",
    0x21: "busyRepeatRequest",
    0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError",
    0x25: "noResponseFromSubnetComponent",
    0x26: "failurePreventsExecutionOfRequestedAction",
    0x31: "requestOutOfRange",
    0x33: "securityAccessDenied",
    0x35: "invalidKey",
    0x36: "exceededNumberOfAttempts",
    0x37: "requiredTimeDelayNotExpired",
    0x70: "uploadDownloadNotAccepted",
    0x71: "transferDataSuspended",
    0x72: "generalProgrammingFailure",
    0x73: "wrongBlockSequenceCounter",
    0x78: "requestCorrectlyReceivedResponsePending",
    0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}


# ============================================================================
# Diagnostic Session Types (Service 0x10 sub-functions)
# ============================================================================

SESSION_NAMES = {
    # ISO 14229-1 standartiniai
    0x01: "default",
    0x02: "programming",
    0x03: "extended",
    0x04: "safetySystem",

    # OEM-specifiniai (matomi realiame sraute)
    0x40: "EOLPF",                # End-of-line programming
    0x41: "BMW_codingSession",
    0x60: "BMW_flashSession",
    0x81: "MB_extended",          # Mercedes pratesta sesija (Actros MP4)
    0x83: "DAF_extended",         # DAF pratesta sesija
    0x85: "MAN_extended",
}


# ============================================================================
# ReadDTCInformation sub-functions (Service 0x19)
# ============================================================================

DTC_SUBFUNCTIONS = {
    0x01: "reportNumberOfDTCByStatusMask",
    0x02: "reportDTCByStatusMask",
    0x03: "reportDTCSnapshotIdentification",
    0x04: "reportDTCSnapshotRecordByDTCNumber",
    0x05: "reportDTCStoredDataByRecordNumber",
    0x06: "reportDTCExtendedDataRecordByDTCNumber",
    0x07: "reportNumberOfDTCBySeverityMaskRecord",
    0x08: "reportDTCBySeverityMaskRecord",
    0x09: "reportSeverityInformationOfDTC",
    0x0A: "reportSupportedDTC",
    0x0B: "reportFirstTestFailedDTC",
    0x0C: "reportFirstConfirmedDTC",
    0x0D: "reportMostRecentTestFailedDTC",
    0x0E: "reportMostRecentConfirmedDTC",
    0x14: "reportDTCFaultDetectionCounter",
    0x15: "reportDTCWithPermanentStatus",
}


# ============================================================================
# Bendrieji DTC status bitai (ISO 14229-1, vienodi visiems UDS ECU)
# ============================================================================

DTC_STATUS_BITS = {
    0x01: "testFailed",
    0x02: "testFailedThisOperationCycle",
    0x04: "pendingDTC",
    0x08: "confirmedDTC",
    0x10: "testNotCompletedSinceLastClear",
    0x20: "testFailedSinceLastClear",
    0x40: "testNotCompletedThisOperationCycle",
    0x80: "warningIndicatorRequested",
}


# ============================================================================
# Helperiai
# ============================================================================

def decode_service(sid):
    """
    Pavadinti SID baita. Palaiko ir uzklausu, ir teigiamu atsakymu (SID + 0x40).

    Pavyzdziai:
        decode_service(0x22) -> "ReadDataByIdentifier"
        decode_service(0x62) -> "ReadDataByIdentifier (positive response)"
        decode_service(0x7F) -> "Negative Response"
        decode_service(0xAB) -> None
    """
    if sid == 0x7F:
        return "Negative Response"
    if sid in UDS_SERVICES:
        return UDS_SERVICES[sid]
    # Teigiamas atsakymas: SID + 0x40
    if sid >= 0x40 and (sid - 0x40) in UDS_SERVICES:
        return f"{UDS_SERVICES[sid - 0x40]} (positive response)"
    return None


def decode_nrc(byte):
    """NRC pavadinimas. Jei nezinomas — grazina '0xXX' string fallback."""
    return NRC_NAMES.get(byte, f"0x{byte:02X}")


def decode_session(byte):
    """Sesijos pavadinimas. Jei nezinomas — grazina '0xXX' string fallback."""
    return SESSION_NAMES.get(byte, f"0x{byte:02X}")


def decode_dtc_subfunc(byte):
    """DTC sub-funkcijos pavadinimas. Jei nezinomas — grazina 'sub=0xXX' fallback."""
    return DTC_SUBFUNCTIONS.get(byte, f"sub=0x{byte:02X}")


def decode_dtc_status(status_byte):
    """
    Iskleisti DTC status baita i aktyvius bitu pavadinimus.

    Grazina sarisa string-u, pvz: ['testFailed', 'confirmedDTC'].
    Tuscias sarisas reiskia kad jokie bitai nera nustatyti (status = 0x00).
    """
    return [name for bit, name in DTC_STATUS_BITS.items() if status_byte & bit]
