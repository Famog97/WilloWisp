"""
ProtocolPort (R-HEX-2 / R-EXT-2) — the industrial-protocol boundary.

Relocated verbatim from ``baru.BaseProtocol`` (M1.4) so the engine depends on this
interface, never on a concrete transport. Concrete protocols (Modbus today, SNMP/…
later) subclass it and register with the protocol manager; adding one needs no
engine edits. ``BaseProtocol`` is kept as a back-compat alias for existing imports.

The default ``start``/``stop``/``check_health`` are concrete no-ops (preserved from
the legacy base, which ``ModbusProtocol`` relies on by NOT overriding them); only
``trigger_alarm``/``reset_alarm`` are required of a concrete protocol.
"""
from __future__ import annotations


class ProtocolPort:
    def __init__(self, config):
        self.config = config
        self.is_healthy = False

    def start(self):
        pass

    def stop(self):
        pass

    def trigger_alarm(self, payload):
        raise NotImplementedError()

    def reset_alarm(self, payload):
        raise NotImplementedError()

    def check_health(self):
        return self.is_healthy


# Back-compat: legacy code imports `BaseProtocol`.
BaseProtocol = ProtocolPort
