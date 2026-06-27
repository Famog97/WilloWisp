"""
adapters/driven/protocol/manager.py  (M3.4 — relocated from baru.ProtocolManager)

Protocol registry (R-EXT-2): resolves a protocol by name, lazily instantiating +
starting it. Adding a protocol = implement ProtocolPort + register here. baru
re-exports ProtocolManager as a shim.
"""
from __future__ import annotations

from adapters.driven.protocol.modbus import ModbusProtocol


class ProtocolManager:
    def __init__(self, config, log_callback=None): 
        self.config = config
        self.active = {}
        self.log_callback = log_callback 
        self.registry = {}
        self.register_protocol("MODBUS", ModbusProtocol)
        
    def register_protocol(self, name, protocol_class):
        self.registry[name.upper()] = protocol_class

    def get_protocol(self, name):
        name = name.upper()
        if name not in self.active:
            if name in self.registry:
                plugin = self.registry[name](self.config, self.log_callback) 
                plugin.start()
                self.active[name] = plugin
            else:
                raise ValueError(f"Protocol '{name}' not found in registry. Add it via register_protocol().")
        return self.active[name]

    def stop_all(self):
        for p in self.active.values():
            try: p.stop()
            except: pass
