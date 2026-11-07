"""
capture_tap.py - A demo tool: records connection B into a file that Wireshark can open.

Normally you capture traffic with Wireshark itself. This tool is useful when you can't
(for example, no admin rights). It sits in the middle of connection B:

    Client app  --->  capture_tap (port 9444)  --->  Filter server (port 9443)

It passes every byte on unchanged, and also writes them into a ".pcap" file
(the file format Wireshark uses). The TLS traffic stays encrypted; the tap can't read it.

Usage (from the project folder):
    python tools/capture_tap.py 9444 127.0.0.1 9443 capture.pcap
Then in config/client.json set "server_port": 9444, start the client, browse a little,
stop the tap with Ctrl+C and open capture.pcap in Wireshark.
In Wireshark: right-click a packet -> Decode As... -> TCP port 9443 -> TLS.
"""

import select
import socket
import struct
import sys
import threading
import time

# Wireshark "link type" 101 = the packets start with an IP header (no Ethernet header).
LINKTYPE_RAW_IP = 101

# Biggest piece of data we put in one recorded packet.
MAX_SEGMENT = 1400

# TCP flags.
FIN = 0x01
SYN = 0x02
PSH = 0x08
ACK = 0x10


class PcapWriter:
    """Writes packets into a .pcap file. Several threads may use it, so it has a lock."""

    def __init__(self, path):
        self.file = open(path, "wb")
        self.lock = threading.Lock()
        # The pcap file header: magic number, version 2.4, time zone 0, accuracy 0,
        # max packet size 65535, link type.
        self.file.write(struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, LINKTYPE_RAW_IP))

    def write_packet(self, packet):
        """Write one packet with the current time."""
        now = time.time()
        seconds = int(now)
        microseconds = int((now - seconds) * 1000000)
        with self.lock:
            self.file.write(struct.pack("<IIII", seconds, microseconds, len(packet), len(packet)))
            self.file.write(packet)
            self.file.flush()

    def close(self):
        self.file.close()


def ip_checksum(header):
    """The standard checksum of an IPv4 header (add 16-bit words, fold, invert)."""
    total = 0
    for i in range(0, len(header), 2):
        total = total + (header[i] << 8) + header[i + 1]
    while total > 0xFFFF:
        total = (total & 0xFFFF) + (total >> 16)
    return (~total) & 0xFFFF


def build_packet(source_ip, source_port, dest_ip, dest_port, seq, ack, flags, payload):
    """Build an IPv4 + TCP packet around 'payload', so Wireshark can show it."""
    tcp_header = struct.pack("!HHIIBBHHH", source_port, dest_port, seq, ack,
                             5 << 4, flags, 65535, 0, 0)
    total_length = 20 + len(tcp_header) + len(payload)
    ip_header = struct.pack("!BBHHHBBH4s4s", 0x45, 0, total_length, 0, 0, 64, 6, 0,
                            socket.inet_aton(source_ip), socket.inet_aton(dest_ip))
    checksum = ip_checksum(ip_header)
    ip_header = ip_header[:10] + struct.pack("!H", checksum) + ip_header[12:]
    return ip_header + tcp_header + payload


class RecordedConnection:
    """Remembers the TCP numbers of one connection, so the recorded packets make sense."""

    def __init__(self, pcap, client_address, server_address):
        self.pcap = pcap
        self.client_ip, self.client_port = client_address
        self.server_ip, self.server_port = server_address
        self.client_seq = 1000   # next byte number sent by the client
        self.server_seq = 5000   # next byte number sent by the server

    def record_open(self):
        """Record the TCP three-way handshake: SYN, SYN-ACK, ACK."""
        self.send_client(SYN, b"")
        self.client_seq = self.client_seq + 1
        self.send_server(SYN | ACK, b"")
        self.server_seq = self.server_seq + 1
        self.send_client(ACK, b"")

    def record_data(self, from_client, data):
        """Record data, cut into pieces of at most MAX_SEGMENT bytes."""
        for start in range(0, len(data), MAX_SEGMENT):
            piece = data[start:start + MAX_SEGMENT]
            if from_client:
                self.send_client(PSH | ACK, piece)
                self.client_seq = self.client_seq + len(piece)
            else:
                self.send_server(PSH | ACK, piece)
                self.server_seq = self.server_seq + len(piece)

    def record_close(self):
        """Record the end of the connection (FIN from the client)."""
        self.send_client(FIN | ACK, b"")

    def send_client(self, flags, payload):
        self.pcap.write_packet(build_packet(self.client_ip, self.client_port, self.server_ip,
                                            self.server_port, self.client_seq, self.server_seq,
                                            flags, payload))

    def send_server(self, flags, payload):
        self.pcap.write_packet(build_packet(self.server_ip, self.server_port, self.client_ip,
                                            self.client_port, self.server_seq, self.client_seq,
                                            flags, payload))


def handle_connection(client_socket, client_address, server_host, server_port, pcap):
    """Pass bytes between the client and the server, and record everything."""
    try:
        server_socket = socket.create_connection((server_host, server_port), timeout=10)
    except OSError as error:
        print("Could not reach the server:", error)
        client_socket.close()
        return

    server_ip = server_socket.getpeername()[0]
    record = RecordedConnection(pcap, client_address, (server_ip, server_port))
    record.record_open()
    print("Recording connection from", client_address[0], "port", client_address[1])

    sockets = [client_socket, server_socket]
    try:
        while True:
            readable, _, _ = select.select(sockets, [], [], 600)
            if len(readable) == 0:
                break
            finished = False
            for source in readable:
                data = source.recv(65536)
                if data == b"":
                    finished = True
                    break
                if source is client_socket:
                    server_socket.sendall(data)
                    record.record_data(True, data)
                else:
                    client_socket.sendall(data)
                    record.record_data(False, data)
            if finished:
                break
    except OSError:
        pass
    finally:
        record.record_close()
        client_socket.close()
        server_socket.close()


def main():
    if len(sys.argv) != 5:
        print("Usage: python tools/capture_tap.py <listen_port> <server_host> <server_port> <output.pcap>")
        return

    listen_port = int(sys.argv[1])
    server_host = sys.argv[2]
    server_port = int(sys.argv[3])
    pcap = PcapWriter(sys.argv[4])

    listen_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen_socket.bind(("127.0.0.1", listen_port))
    listen_socket.listen(10)
    print("Tap listening on 127.0.0.1:" + str(listen_port) + ", forwarding to "
          + server_host + ":" + str(server_port) + ", writing " + sys.argv[4])

    try:
        while True:
            client_socket, client_address = listen_socket.accept()
            thread = threading.Thread(target=handle_connection, daemon=True,
                                      args=(client_socket, client_address, server_host, server_port, pcap))
            thread.start()
    except KeyboardInterrupt:
        print("\nStopped. Open the .pcap file in Wireshark.")
    finally:
        listen_socket.close()
        pcap.close()


if __name__ == "__main__":
    main()
