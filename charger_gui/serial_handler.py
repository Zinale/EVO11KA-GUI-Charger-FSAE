import re
from typing import Optional, List
from PyQt6.QtCore import QThread, pyqtSignal
import serial
import serial.tools.list_ports


class SerialMessage:
    def __init__(self, direction: str, can_id: int, data: List[int], raw: str):
        self.direction = direction  # "Rx" o "Tx"
        self.can_id = can_id
        self.data = data
        self.raw = raw
    
    def __repr__(self):
        data_hex = ' '.join(f'{b:02X}' for b in self.data)
        return f"CAN {self.direction} ID=0x{self.can_id:03X} Data=[{data_hex}]"


class SerialHandler(QThread):
    """Thread per gestire la comunicazione seriale"""
    
    # Segnali PyQt
    message_received = pyqtSignal(SerialMessage)
    connection_status = pyqtSignal(bool, str)  # (connected, message)
    error_occurred = pyqtSignal(str)
    
    def __init__(self):
        super().__init__()
        self.serial_port: Optional[serial.Serial] = None
        self.running = False
        self.port_name = ""
        self.baudrate = 115200
        
        # Pattern espressione regolare: "CanBus Rx/Tx {ID} {Contenuto}"
        # Esempi:
        # "CanBus Rx 0x618 12 34 56 78 9A BC DE F0"
        # "CanBus Tx 0x610 AA BB CC DD"
        self.pattern = re.compile(
            r'CanBus\s+(Rx|Tx)\s+(?:0x)?([0-9A-Fa-f]+)\s+((?:[0-9A-Fa-f]{2}\s*)+)',
            re.IGNORECASE
        )
    
    def set_port(self, port_name: str, baudrate: int = 115200):
        """Imposta porta seriale e baudrate"""
        self.port_name = port_name
        self.baudrate = baudrate
    
    def connect(self) -> bool:
        """Connette alla porta seriale"""
        try:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
            
            self.serial_port = serial.Serial(
                port=self.port_name,
                baudrate=self.baudrate,
                timeout=0.1
            )
            
            self.connection_status.emit(True, f"Connesso a {self.port_name}")
            return True
            
        except serial.SerialException as e:
            self.connection_status.emit(False, f"Errore connessione: {e}")
            self.error_occurred.emit(str(e))
            return False
    
    def disconnect(self):
        """Disconnette dalla porta seriale"""
        self.running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            self.connection_status.emit(False, "Disconnesso")
    
    def send_message(self, message: str):
        """Invia un messaggio sulla seriale"""
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write(f"{message}\n".encode())
            except serial.SerialException as e:
                self.error_occurred.emit(f"Errore invio: {e}")
    
    def parse_message(self, line: str) -> Optional[SerialMessage]:
        """
        Verifica che sia una RE attesa
        Analizza una riga ricevuta dalla seriale
        
        Formato atteso: "CanBus Rx/Tx {ID} {Contenuto}"
        Esempi:
            "CanBus Rx 0x618 12 34 56 78 9A BC DE F0"
            "CanBus Tx 610 AA BB CC DD EE FF"
        """
        match = self.pattern.match(line.strip())
        if not match:
            return None
        direction = match.group(1)  # "Rx" o "Tx"
        can_id_str = match.group(2)
        data_str = match.group(3).strip()
        
        try:
            # Converti ID (può essere hex o decimale)
            can_id = int(can_id_str, 16)
            
            # Converti dati (separati da spazi)
            data_bytes = [int(b, 16) for b in data_str.split()]
            
            return SerialMessage(direction, can_id, data_bytes, line)
            
        except ValueError as e:
            self.error_occurred.emit(f"Errore parsing: {e} - Riga: {line}")
            return None
    
    def run(self):
        """Thread principale per lettura seriale"""
        self.running = True
        buffer = ""
        
        while self.running:
            if not self.serial_port or not self.serial_port.is_open:
                self.msleep(50)    #delay
                continue
            
            try:
                # Legge dalla seriale
                if self.serial_port.in_waiting > 0:         #in buffer
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    buffer += data.decode('utf-8', errors='ignore')
                    
                    # Processa righe complete e separate
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        
                        if line:
                            # Analizza il messaggio
                            msg = self.parse_message(line)
                            if msg:
                                self.message_received.emit(msg)
                
                self.msleep(10)  # Piccola pausa per non sovraccaricare CPU
                
            except serial.SerialException as e:
                self.error_occurred.emit(f"Errore lettura: {e}")
                self.disconnect()
                break
            except Exception as e:
                self.error_occurred.emit(f"Errore inaspettato: {e}")
    
    def stop(self):
        """Ferma il thread"""
        self.running = False
        self.disconnect()
        self.wait()


def list_serial_ports() -> List[str]:
    """Restituisce lista delle porte seriali disponibili (aperte)"""
    ports = serial.tools.list_ports.comports()
    return [port.device for port in ports]