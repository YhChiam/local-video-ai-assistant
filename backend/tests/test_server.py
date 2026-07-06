import socket
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import find_available_port


class PortSelectionTests(unittest.TestCase):
    def test_find_available_port_skips_busy_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy_sock:
            busy_sock.bind(("127.0.0.1", 0))
            busy_port = busy_sock.getsockname()[1]

            port = find_available_port(start_port=busy_port, max_attempts=3)

            self.assertNotEqual(port, busy_port)
            self.assertGreaterEqual(port, busy_port + 1)


if __name__ == "__main__":
    unittest.main()
