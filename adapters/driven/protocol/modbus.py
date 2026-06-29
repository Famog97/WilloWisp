"""
adapters/driven/protocol/modbus.py  (M3.4 — relocated from baru.ModbusProtocol)

The Modbus TCP server protocol adapter (implements the ProtocolPort). pymodbus is
guarded so the module imports even where pymodbus is unavailable; ModbusProtocol is
only instantiated when a run uses it. baru re-exports ModbusProtocol as a shim.
"""
from __future__ import annotations

import logging
import re
import threading

from core.ports.protocol import ProtocolPort, BaseProtocol
from core.domain.io_point_states import write_register, field_width, apply_value, normalize_register

logger = logging.getLogger("AutoClick")

try:
    import asyncio
    from pymodbus.server import ModbusTcpServer
    from pymodbus.datastore import ModbusSequentialDataBlock, ModbusDeviceContext, ModbusServerContext
    PYMODBUS_AVAILABLE = True
except Exception as _e:
    PYMODBUS_AVAILABLE = False


class ModbusProtocol(BaseProtocol):
    def __init__(self, config, log_callback=None):
        self.is_healthy = False
        self.config = config
        self.log_callback = log_callback
        self.slave_id = 1
        
        # Start at address 0 so register 0 (e.g. ISCS 40000 -> 0) is addressable.
        block = lambda: ModbusSequentialDataBlock(0, [0]*10001)
        store = ModbusDeviceContext(di=block(), co=block(), hr=block(), ir=block())
        self.context = ModbusServerContext(devices=store, single=True)
        
        self.server = None
        self.loop = None
        
        self.server_thread = threading.Thread(target=self._start_server_thread, daemon=True)
        self.server_thread.name = "ModbusServerThread"
        self.server_thread.start()

    def _start_server_thread(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.is_healthy = True
            self.loop.run_until_complete(self._run_server())
        except Exception as e:
            logger.error(f"Modbus Thread Error: {e}")
            self.is_healthy = False
        finally:
            self.loop.close()

    async def _run_server(self):
        modbus_port = self.config.get("modbus_port", 502)
        logger.info(f"Starting ISCS Modbus Server on 0.0.0.0:{modbus_port}")
        try: 
            self.server = ModbusTcpServer(
                self.context, address=("0.0.0.0", modbus_port),
                trace_packet=self._on_packet, trace_connect=self._on_connect
            )
            await self.server.serve_forever()
        except Exception as e: 
            logger.error(f"Modbus failed to start: {e}")
            self.is_healthy = False

    def stop(self):
        self.is_healthy = False
        if self.server:
            try:
                # Explicitly close active listening sockets
                if self.loop and self.loop.is_running():
                    self.loop.call_soon_threadsafe(self.server.shutdown)
                else:
                    self.server.shutdown()
                logger.info("Modbus server sockets shut down cleanly.")
            except Exception as e:
                logger.warning(f"Failed to shut down Modbus server explicitly: {e}")
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)

    def _on_packet(self, sending, data):
        direction = "Tx" if sending else "Rx"
        try:
            if len(data) >= 7: 
                unit_id = data[6]
                function_code = data[7] if len(data) > 7 else "N/A"
                fc_name = f"FC{function_code:02d}" if isinstance(function_code, int) else "N/A"
                logging.getLogger("modbus_traffic").debug(f"[{direction}] Unit ID {unit_id}, FC {fc_name} - {data.hex()}")
        except Exception: pass
        return data

    def _on_connect(self, connected, *args):
        status = "CONNECTED" if connected else "DISCONNECTED"
        client = args[0] if args else "Unknown"
        logging.getLogger("modbus_traffic").info(f"CLIENT {status}: {client}")

    def _get_slave(self):
        return self.context[0]

    def _write_coil_or_reg(self, p, value):
        payload = p.get('payload', p)
        raw_fc  = str(payload.get('fc', p.get('fc', '3'))).strip().upper()
        m       = re.search(r'(\d+)', raw_fc)
        fc_num  = int(m.group(1)) if m else 3

        reg   = normalize_register(write_register(payload))   # ISCS addr, 4xxxx -> PDU offset
        bit   = int(payload.get('bit',  p.get('bit',  0)))
        width = field_width(payload.get('addr_size'), p.get('states', {}))
        val   = int(value)
        slave = self._get_slave()

        mb_log = logging.getLogger("modbus_traffic")
        point_id = p.get('point_id', payload.get('point_id', '?'))
        mb_log.info(f"[WRITE val={val}] point={point_id} fc={fc_num} reg={reg} bit={bit} width={width}")

        if fc_num in [1, 5]: slave.setValues(1, reg, [bool(val)])
        elif fc_num == 2: slave.setValues(2, reg, [bool(val)])
        elif fc_num == 4: slave.setValues(4, reg, [val & 0xFFFF])
        else: # Default for 3, 6, 16 and generic registers — write the value into its bit-field
            current = slave.getValues(3, reg, 1)
            cur_val = current[0] if current else 0
            new_val = apply_value(cur_val, val, bit, width)   # width=1 == old set/clear bit
            slave.setValues(3, reg, [new_val])

    def write_value(self, p, value):
        """Write an arbitrary IO-list value (0..N) to the point's register field."""
        self._write_coil_or_reg(p, value)

    def trigger_alarm(self, p): self._write_coil_or_reg(p, 1)
    def reset_alarm(self, p):   self._write_coil_or_reg(p, 0)
